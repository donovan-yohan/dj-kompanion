# server/analysis_store.py
"""Read/write analysis results as sidecar .meta.json files."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from server.models import AnalysisResult

logger = logging.getLogger(__name__)


def sidecar_path(analysis_dir: Path, audio_path: Path) -> Path:
    """Determine the sidecar .meta.json path for an audio file.

    Uses the audio file's stem plus a short hash of the full path to
    avoid collisions when files in different directories share a name.
    """
    stem = audio_path.stem
    path_hash = hashlib.sha256(str(audio_path).encode()).hexdigest()[:4]
    return analysis_dir / f"{stem}_{path_hash}.meta.json"


def save_analysis(analysis_dir: Path, audio_path: Path, result: AnalysisResult) -> Path:
    """Write analysis result to a sidecar .meta.json file. Returns the output path."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out_path = sidecar_path(analysis_dir, audio_path)
    data = result.model_dump()
    out_path.write_text(json.dumps(data, indent=2))
    logger.info("Saved analysis to %s", out_path)
    return out_path


def load_analysis(path: Path) -> AnalysisResult | None:
    """Load analysis result from a .meta.json file. Returns None if file doesn't exist."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return AnalysisResult.model_validate(data)
