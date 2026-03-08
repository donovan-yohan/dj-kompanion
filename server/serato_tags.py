from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from serato_tools.track_cues_v2 import TrackCuesV2  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from pathlib import Path

    from server.models import AnalysisResult

logger = logging.getLogger(__name__)

# Serato cue colors, one per index (hot-cue slot 0–7).
_CUE_COLORS: list[bytes] = [
    TrackCuesV2.CueColors.RED.value,
    TrackCuesV2.CueColors.ORANGE.value,
    TrackCuesV2.CueColors.YELLOW.value,
    TrackCuesV2.CueColors.LIMEGREEN2.value,
    TrackCuesV2.CueColors.CYAN.value,
    TrackCuesV2.CueColors.BLUE1.value,
    TrackCuesV2.CueColors.PURPLE1.value,
    TrackCuesV2.CueColors.PINK.value,
]

_MAX_CUES = 8


def _build_cue_name(label: str, bars: int) -> str:
    bar_word = "bar" if bars == 1 else "bars"
    return f"{label} ({bars} {bar_word})"


def _make_cue_entry(index: int, position_ms: int, name: str) -> TrackCuesV2.CueEntry:
    """Build a CueEntry with sensible defaults for unused fields."""
    color = _CUE_COLORS[index % len(_CUE_COLORS)]
    return TrackCuesV2.CueEntry(
        field1=b"\x00",
        index=index,
        position=position_ms,
        field4=b"\x00",
        color=color,
        field6=b"\x00\x00",
        name=name,
    )


def write_serato_cues(filepath: Path, result: AnalysisResult) -> bool:
    """Write Serato Markers2 GEOB cue points into an MP3 file.

    Returns True on success, False if the file is not MP3 or on any error.
    Best-effort: failures are logged but never raised.
    """
    if filepath.suffix.lower() != ".mp3":
        return False

    try:
        segments = result.segments[:_MAX_CUES]
        if not segments:
            logger.debug("No segments to write for %s", filepath)
            return False

        cues: list[TrackCuesV2.CueEntry] = []
        for i, seg in enumerate(segments):
            position_ms = int(seg.start * 1000)
            name = _build_cue_name(seg.label, seg.bars)
            cues.append(_make_cue_entry(i, position_ms, name))

        tags = TrackCuesV2(str(filepath))

        def _set_cues(
            track: TrackCuesV2.TrackCuesInfo,
        ) -> TrackCuesV2.TrackCuesInfo:
            return TrackCuesV2.TrackCuesInfo(
                bpm_lock=track.bpm_lock,
                color=track.color,
                cues=cues,
                loops=track.loops,
                flips=track.flips,
                unknown=track.unknown,
            )

        tags.modify_entries(_set_cues)
        tags.save(force=True)
        logger.info("Wrote %d Serato cues to %s", len(cues), filepath)
        return True
    except Exception:
        logger.exception("Failed to write Serato cues to %s", filepath)
        return False
