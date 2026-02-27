from __future__ import annotations

from typing import Any

import yt_dlp  # type: ignore[import-untyped]
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.config import load_config
from server.downloader import DownloadError, download_audio, extract_metadata
from server.enrichment import basic_enrich, is_claude_available
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

    try:
        filepath = await download_audio(
            req.url,
            cfg.output_dir,
            filename,
            req.format,
        )
    except DownloadError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "download_failed", "message": e.message, "url": e.url},
        ) from e

    try:
        final_path = tag_file(filepath, req.metadata)
    except TaggingError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "tagging_failed",
                "message": e.message,
                "filepath": str(e.filepath),
            },
        ) from e

    return DownloadResponse(status="complete", filepath=str(final_path))
