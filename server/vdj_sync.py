"""VDJ database sync — batch-write analysis results to database.xml."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path as _Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from server.analysis_store import load_analysis
from server.track_db import get_unsynced, mark_synced
from server.vdj import write_to_vdj_database

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    synced: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    refused: bool = False


def is_vdj_running() -> bool:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["pgrep", "-x", "VirtualDJ"], capture_output=True, check=False
        )
    else:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq VirtualDJ.exe"],
            capture_output=True,
            check=False,
        )
    return result.returncode == 0


def sync_vdj(db_path: Path, vdj_database_path: Path, max_cues: int = 8) -> SyncResult:
    result = SyncResult()

    if is_vdj_running():
        logger.warning("VirtualDJ is running — refusing to write to database.xml")
        result.refused = True
        return result

    unsynced = get_unsynced(db_path)
    if not unsynced:
        logger.info("No tracks to sync")
        return result

    for track in unsynced:
        if track.analysis_path is None:
            result.skipped += 1
            continue

        analysis = load_analysis(_Path(track.analysis_path))
        if analysis is None:
            result.errors.append(f"Missing sidecar: {track.analysis_path}")
            continue

        try:
            written = write_to_vdj_database(
                vdj_database_path, track.filepath, analysis, max_cues=max_cues
            )
            if written:
                mark_synced(db_path, track.filepath)
                result.synced += 1
            else:
                result.skipped += 1
        except Exception as e:
            result.errors.append(f"{track.filepath}: {e}")
            logger.error("Failed to sync %s", track.filepath, exc_info=True)

    logger.info(
        "Sync complete: %d synced, %d skipped, %d errors",
        result.synced,
        result.skipped,
        len(result.errors),
    )
    return result
