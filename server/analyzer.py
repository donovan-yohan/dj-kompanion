"""Audio analysis client — proxies requests to the analyzer container."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from pathlib import Path

from server.analysis_store import save_analysis
from server.models import AnalysisResult
from server.serato_tags import write_serato_cues
from server.track_db import mark_analyzed, mark_analyzing, mark_failed

logger = logging.getLogger(__name__)

# Default timeout: 10 minutes (ML analysis is slow, especially first run with model download)
_ANALYZE_TIMEOUT = 600.0


async def analyze_audio(
    filepath: Path,
    db_path: Path | None = None,
    analysis_dir: Path | None = None,
    analyzer_url: str = "http://localhost:9235",
    output_dir: Path | None = None,
) -> AnalysisResult | None:
    """Request audio analysis from the analyzer container.

    Translates the host filepath to the container's /audio mount path,
    calls the analyzer service, and optionally writes results to a sidecar
    .meta.json file and updates the SQLite track database.

    Returns AnalysisResult on success, None on failure.
    Never raises — all errors are caught and logged.
    """
    if db_path is not None:
        mark_analyzing(db_path, str(filepath))

    container_path = _to_container_path(filepath, output_dir)

    try:
        async with httpx.AsyncClient(timeout=_ANALYZE_TIMEOUT) as client:
            response = await client.post(
                f"{analyzer_url}/analyze",
                json={"filepath": container_path},
            )
    except httpx.ConnectError:
        msg = (
            f"Cannot reach analyzer service at {analyzer_url} — is the container running? "
            "(docker compose up -d)"
        )
        logger.error(msg)
        if db_path is not None:
            mark_failed(db_path, str(filepath), msg)
        return None
    except httpx.TimeoutException:
        msg = (
            f"Analyzer request timed out after {_ANALYZE_TIMEOUT:.0f}s — analysis may still be "
            "running or model download may be in progress"
        )
        logger.error(msg)
        if db_path is not None:
            mark_failed(db_path, str(filepath), msg)
        return None
    except Exception:
        logger.error("Failed to call analyzer service", exc_info=True)
        if db_path is not None:
            mark_failed(db_path, str(filepath), "Failed to call analyzer service")
        return None

    if response.status_code != 200:
        msg = f"Analyzer returned HTTP {response.status_code}: {response.text}"
        logger.error(msg)
        if db_path is not None:
            mark_failed(db_path, str(filepath), msg)
        return None

    data = response.json()
    if data.get("status") != "ok" or data.get("analysis") is None:
        msg = f"Analyzer returned error: {data.get('message', 'unknown')}"
        logger.error(msg)
        if db_path is not None:
            mark_failed(db_path, str(filepath), msg)
        return None

    result = AnalysisResult.model_validate(data["analysis"])

    if analysis_dir is not None:
        out_path = save_analysis(analysis_dir, filepath, result)

        # Write Serato GEOB tags for VDJ auto-import (best-effort)
        try:
            write_serato_cues(filepath, result)
        except Exception:
            logger.warning("Serato tag write failed for %s", filepath, exc_info=True)

        if db_path is not None:
            mark_analyzed(db_path, str(filepath), str(out_path))

    logger.info(
        "Analysis complete for %s: BPM=%.1f, Key=%s, %d segments",
        filepath,
        result.bpm,
        result.key,
        len(result.segments),
    )
    return result


def _to_container_path(filepath: Path, output_dir: Path | None) -> str:
    """Translate a host filepath to the container's /audio mount path.

    Example: ~/Music/DJ Library/Artist - Title.m4a -> /audio/Artist - Title.m4a
    """
    if output_dir is not None:
        try:
            relative = filepath.relative_to(output_dir)
            return f"/audio/{relative}"
        except ValueError:
            pass
    # Fallback: use filename only
    return f"/audio/{filepath.name}"
