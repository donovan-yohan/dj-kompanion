"""Audio analysis client — proxies requests to the analyzer container."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from server.models import AnalysisResult

logger = logging.getLogger(__name__)

# Default timeout: 10 minutes (ML analysis is slow, especially first run with model download)
_ANALYZE_TIMEOUT = 600.0


async def analyze_audio(
    filepath: Path,
    vdj_db_path: Path | None = None,
    max_cues: int = 8,
    analyzer_url: str = "http://localhost:9235",
    output_dir: Path | None = None,
) -> AnalysisResult | None:
    """Request audio analysis from the analyzer container.

    Translates the host filepath to the container's /audio mount path,
    calls the analyzer service, and optionally writes results to VDJ database.

    Returns AnalysisResult on success, None on failure.
    Never raises — all errors are caught and logged.
    """
    container_path = _to_container_path(filepath, output_dir)

    try:
        async with httpx.AsyncClient(timeout=_ANALYZE_TIMEOUT) as client:
            response = await client.post(
                f"{analyzer_url}/analyze",
                json={"filepath": container_path},
            )
    except httpx.ConnectError:
        logger.error(
            "Cannot reach analyzer service at %s — is the container running? "
            "(docker compose up -d)",
            analyzer_url,
        )
        return None
    except Exception:
        logger.error("Failed to call analyzer service", exc_info=True)
        return None

    if response.status_code != 200:
        logger.error("Analyzer returned HTTP %d: %s", response.status_code, response.text)
        return None

    data = response.json()
    if data.get("status") != "ok" or data.get("analysis") is None:
        logger.error("Analyzer returned error: %s", data.get("message", "unknown"))
        return None

    result = AnalysisResult.model_validate(data["analysis"])

    # VDJ write stays in the main server
    if vdj_db_path is not None:
        try:
            from server.vdj import write_to_vdj_database

            write_to_vdj_database(vdj_db_path, str(filepath), result, max_cues=max_cues)
            result.vdj_written = True
        except Exception:
            logger.warning("Failed to write to VDJ database", exc_info=True)

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
