from __future__ import annotations

import asyncio
from typing import Any, Literal

import yt_dlp  # type: ignore[import-untyped]
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import load_config
from server.downloader import DownloadError, download_audio, extract_metadata
from server.enrichment import basic_enrich, is_claude_available, merge_metadata, try_enrich_metadata
from server.models import (
    DownloadRequest,
    DownloadResponse,
    HealthResponse,
    PreviewRequest,
    PreviewResponse,
)
from server.tagger import TaggingError, build_download_filename, tag_file

app = FastAPI(title="dj-kompanion", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail: Any = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "error", "message": str(detail)},
    )


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    yt_dlp_version: str = str(yt_dlp.version.__version__)
    claude_available = await is_claude_available()
    return HealthResponse(
        status="ok",
        yt_dlp_version=yt_dlp_version,
        claude_available=claude_available,
    )


@app.post("/api/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest) -> PreviewResponse:
    try:
        raw = await extract_metadata(req.url)
    except DownloadError as e:
        raise HTTPException(
            status_code=404,
            detail={"error": "extraction_failed", "message": e.message, "url": e.url},
        ) from e

    enriched = basic_enrich(raw)
    return PreviewResponse(raw=raw, enriched=enriched, enrichment_source="none")


@app.post("/api/download", response_model=DownloadResponse)
async def download(req: DownloadRequest) -> DownloadResponse:
    cfg = load_config()

    filename = build_download_filename(req.metadata.artist, req.metadata.title)
    use_llm = cfg.llm.enabled and await is_claude_available()

    enrichment_source: Literal["claude", "basic", "none"]

    if use_llm:
        results = await asyncio.gather(
            download_audio(req.url, cfg.output_dir, filename, req.format),
            try_enrich_metadata(req.raw, model=cfg.llm.model),
            return_exceptions=True,
        )
        filepath_result, claude_result = results

        if isinstance(filepath_result, DownloadError):
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "download_failed",
                    "message": filepath_result.message,
                    "url": filepath_result.url,
                },
            ) from filepath_result
        if isinstance(filepath_result, BaseException):
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "download_failed",
                    "message": str(filepath_result),
                    "url": req.url,
                },
            ) from filepath_result

        filepath = filepath_result

        if isinstance(claude_result, BaseException) or claude_result is None:
            final_metadata = merge_metadata(
                req.metadata, basic_enrich(req.raw), req.user_edited_fields
            )
            enrichment_source = "basic"
        else:
            final_metadata = merge_metadata(req.metadata, claude_result, req.user_edited_fields)
            enrichment_source = "claude"
    else:
        try:
            filepath = await download_audio(req.url, cfg.output_dir, filename, req.format)
        except DownloadError as e:
            raise HTTPException(
                status_code=500,
                detail={"error": "download_failed", "message": e.message, "url": e.url},
            ) from e
        final_metadata = req.metadata
        enrichment_source = "none"

    try:
        final_path = tag_file(filepath, final_metadata)
    except TaggingError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "tagging_failed",
                "message": e.message,
                "filepath": str(e.filepath),
            },
        ) from e

    return DownloadResponse(
        status="complete",
        filepath=str(final_path),
        enrichment_source=enrichment_source,
    )
