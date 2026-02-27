"""Virtual DJ database.xml writer for analysis results."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from server.models import AnalysisResult, SegmentInfo

logger = logging.getLogger(__name__)

# Priority order for filling cue slots (highest priority first)
CUE_PRIORITY: list[str] = [
    "Drop",
    "Buildup",
    "Breakdown",
    "Intro",
    "Outro",
    "Verse",
    "Bridge",
    "Instrumental",
    "Solo",
    "Chorus",
]


def bpm_to_seconds_per_beat(bpm: float) -> float:
    """Convert BPM to VDJ's seconds-per-beat format."""
    return 60.0 / bpm


def build_cue_name(segment: SegmentInfo) -> str:
    """Build a cue point name like 'Drop 1 (16 bars)'."""
    bar_word = "bar" if segment.bars == 1 else "bars"
    return f"{segment.label} ({segment.bars} {bar_word})"


def prioritize_cues(
    segments: list[SegmentInfo],
    max_cues: int = 8,
) -> list[SegmentInfo]:
    """Select up to max_cues segments, prioritized by DJ importance.

    Segments are sorted by priority (drops first), then by position within
    each priority level.
    """

    def priority_key(seg: SegmentInfo) -> tuple[int, float]:
        # Strip bar count suffix if present: "Drop 1 (16 bars)" -> "Drop 1"
        name = seg.label.split(" (")[0]
        # Strip trailing numbering: "Drop 1" -> "Drop"
        parts = name.rsplit(" ", 1)
        base = parts[0] if len(parts) == 2 and parts[1].isdigit() else name
        try:
            rank = CUE_PRIORITY.index(base)
        except ValueError:
            rank = len(CUE_PRIORITY)
        return (rank, seg.start)

    sorted_segs = sorted(segments, key=priority_key)
    selected = sorted_segs[:max_cues]
    # Re-sort by position for natural cue numbering
    return sorted(selected, key=lambda s: s.start)


def write_to_vdj_database(
    db_path: Path,
    filepath: str,
    result: AnalysisResult,
    max_cues: int = 8,
) -> None:
    """Write analysis results to VDJ database.xml.

    Creates or updates the Song element for the given filepath.
    Silently skips if db_path does not exist.
    """
    if not db_path.exists():
        logger.warning("VDJ database not found at %s, skipping", db_path)
        return

    try:
        tree = ET.parse(db_path)
    except ET.ParseError:
        logger.warning("Failed to parse VDJ database at %s", db_path)
        return

    root = tree.getroot()

    # Find or create Song element
    song = root.find(f".//Song[@FilePath='{filepath}']")
    if song is None:
        song = ET.SubElement(root, "Song")
        song.set("FilePath", filepath)
    else:
        # Clear existing auto-generated POIs and Scan
        for child in list(song):
            song.remove(child)

    # Write Scan element
    scan = ET.SubElement(song, "Scan")
    scan.set("Version", "801")
    scan.set("Bpm", str(bpm_to_seconds_per_beat(result.bpm)))
    scan.set("Key", result.key)

    # Write beatgrid anchor (first downbeat)
    if result.downbeats:
        beatgrid = ET.SubElement(song, "Poi")
        beatgrid.set("Pos", str(result.downbeats[0]))
        beatgrid.set("Type", "beatgrid")

    # Write prioritized cue points
    cues = prioritize_cues(result.segments, max_cues=max_cues)
    for i, seg in enumerate(cues, start=1):
        poi = ET.SubElement(song, "Poi")
        poi.set("Name", build_cue_name(seg))
        poi.set("Pos", str(seg.start))
        poi.set("Num", str(i))

    # Write back
    tree.write(str(db_path), encoding="UTF-8", xml_declaration=True)
    logger.info("Wrote %d cue points to VDJ database for %s", len(cues), filepath)
