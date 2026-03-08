from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

import yt_dlp  # type: ignore[import-untyped]
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from server.analyzer import analyze_audio
from server.config import CONFIG_DIR, load_config
from server.downloader import DownloadError, download_audio, extract_metadata, resolve_playlist
from server.enrichment import basic_enrich, is_claude_available, merge_metadata, try_enrich_metadata
from server.logging_config import setup_logging
from server.metadata_lookup import MetadataCandidate, search_metadata
from server.models import (
    DownloadRequest,
    DownloadResponse,
    HealthResponse,
    PlaylistTrack,
    ReanalyzeRequest,
    ReanalyzeResponse,
    ResolvePlaylistRequest,
    ResolvePlaylistResponse,
    RetagRequest,
    RetagResponse,
    SyncVdjResponse,
    TracksResponse,
    TrackStatus,
)
from server.tagger import TaggingError, build_download_filename, tag_file
from server.track_db import get_all_tracks, get_track, init_db, upsert_track
from server.vdj_sync import sync_vdj

logger = logging.getLogger(__name__)

setup_logging()

# Initialize track database on startup
init_db(CONFIG_DIR / "tracks.db")

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


@app.post("/api/download", response_model=DownloadResponse)
async def download(req: DownloadRequest) -> DownloadResponse:
    cfg = load_config()

    # Extract raw metadata if not provided (simplified flow)
    raw = req.raw
    if raw is None:
        try:
            raw = await extract_metadata(req.url, cookies=req.cookies)
        except DownloadError as e:
            raise HTTPException(
                status_code=500,
                detail={"error": "extraction_failed", "message": e.message, "url": e.url},
            ) from e

    filename = build_download_filename(req.metadata.artist, req.metadata.title)
    use_llm = cfg.llm.enabled and await is_claude_available()

    enrichment_source: Literal["api+claude", "claude", "basic", "none"]

    if use_llm:
        basic = basic_enrich(raw)

        if cfg.metadata_lookup.enabled:
            api_task = search_metadata(
                basic.artist,
                basic.title,
                lastfm_api_key=cfg.metadata_lookup.lastfm_api_key,
                search_limit=cfg.metadata_lookup.search_limit,
                user_agent=cfg.metadata_lookup.musicbrainz_user_agent,
            )
        else:

            async def _empty_search() -> list[MetadataCandidate]:
                return []

            api_task = _empty_search()

        results = await asyncio.gather(
            download_audio(req.url, cfg.output_dir, filename, req.format, cookies=req.cookies),
            api_task,
            return_exceptions=True,
        )
        filepath_result, candidates_result = results

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
            if not isinstance(filepath_result, Exception):
                raise filepath_result
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "download_failed",
                    "message": str(filepath_result),
                    "url": req.url,
                },
            ) from filepath_result

        filepath = filepath_result

        candidates = [] if isinstance(candidates_result, BaseException) else candidates_result

        claude_result = await try_enrich_metadata(raw, model=cfg.llm.model, candidates=candidates)

        if claude_result is not None and candidates:
            enrichment_source = "api+claude"
            final_metadata = merge_metadata(req.metadata, claude_result, req.user_edited_fields)
        elif claude_result is not None:
            enrichment_source = "claude"
            final_metadata = merge_metadata(req.metadata, claude_result, req.user_edited_fields)
        else:
            enrichment_source = "basic"
            final_metadata = merge_metadata(req.metadata, basic, req.user_edited_fields)
    else:
        try:
            filepath = await download_audio(
                req.url, cfg.output_dir, filename, req.format, cookies=req.cookies
            )
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

    # Insert track into SQLite and fire analysis in background
    db_path = CONFIG_DIR / "tracks.db"
    upsert_track(db_path, str(final_path))

    if cfg.analysis.enabled:
        analysis_dir = CONFIG_DIR / "analysis"
        asyncio.create_task(
            analyze_audio(
                final_path,
                db_path=db_path,
                analysis_dir=analysis_dir,
                analyzer_url=cfg.analysis.analyzer_url,
                output_dir=cfg.output_dir,
            )
        )

    return DownloadResponse(
        status="complete",
        filepath=str(final_path),
        enrichment_source=enrichment_source,
        metadata=final_metadata,
    )


@app.post("/api/retag", response_model=RetagResponse)
async def retag(req: RetagRequest) -> RetagResponse:
    filepath = Path(req.filepath)
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "file_not_found", "message": f"File not found: {req.filepath}"},
        )

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

    return RetagResponse(status="ok", filepath=str(final_path))


@app.post("/api/resolve-playlist", response_model=ResolvePlaylistResponse)
async def resolve_playlist_endpoint(req: ResolvePlaylistRequest) -> ResolvePlaylistResponse:
    try:
        playlist_title, tracks = await resolve_playlist(req.url, cookies=req.cookies)
    except DownloadError as e:
        raise HTTPException(
            status_code=404,
            detail={"error": "playlist_resolve_failed", "message": e.message, "url": e.url},
        ) from e

    return ResolvePlaylistResponse(
        playlist_title=playlist_title,
        tracks=[PlaylistTrack(url=url, title=title) for url, title in tracks],
    )


@app.post("/api/sync-vdj", response_model=SyncVdjResponse)
async def sync_vdj_endpoint() -> SyncVdjResponse:
    cfg = load_config()
    db_path = CONFIG_DIR / "tracks.db"
    result = sync_vdj(db_path, cfg.analysis.vdj_database, max_cues=cfg.analysis.max_cues)
    return SyncVdjResponse(
        status="refused" if result.refused else "ok",
        synced=result.synced,
        skipped=result.skipped,
        errors=result.errors,
        refused=result.refused,
    )


@app.get("/api/tracks", response_model=TracksResponse)
async def tracks_endpoint() -> TracksResponse:
    db_path = CONFIG_DIR / "tracks.db"
    rows = get_all_tracks(db_path)
    tracks = [
        TrackStatus(
            filepath=r.filepath,
            status=r.status,
            analysis_path=r.analysis_path,
            error=r.error,
            analyzed_at=r.analyzed_at,
            synced_at=r.synced_at,
        )
        for r in rows
    ]
    return TracksResponse(tracks=tracks)


@app.post("/api/reanalyze", response_model=ReanalyzeResponse)
async def reanalyze_endpoint(req: ReanalyzeRequest) -> ReanalyzeResponse:
    db_path = CONFIG_DIR / "tracks.db"
    track = get_track(db_path, req.filepath)
    if track is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Track not found: {req.filepath}"},
        )
    cfg = load_config()
    upsert_track(db_path, req.filepath)  # resets to 'downloaded'
    analysis_dir = CONFIG_DIR / "analysis"
    asyncio.create_task(
        analyze_audio(
            Path(req.filepath),
            db_path=db_path,
            analysis_dir=analysis_dir,
            analyzer_url=cfg.analysis.analyzer_url,
            output_dir=cfg.output_dir,
        )
    )
    return ReanalyzeResponse(status="queued")
