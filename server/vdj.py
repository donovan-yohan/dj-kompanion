"""Virtual DJ database.xml writer for analysis results."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from io import BytesIO
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

    # Find existing Song element — only modify songs VDJ has already scanned.
    # Creating a new Song entry before VDJ's own scan causes database corruption.
    song = next((s for s in root.findall("Song") if s.get("FilePath") == filepath), None)
    if song is None:
        logger.info("Song not yet in VDJ database, skipping cue write for %s", filepath)
        return

    # Remove only our cue POIs (Type="cue") — leave VDJ's own elements untouched
    for child in list(song):
        if child.tag == "Poi" and child.get("Type") == "cue":
            song.remove(child)

    # Write prioritized cue points
    cues = prioritize_cues(result.segments, max_cues=max_cues)
    for i, seg in enumerate(cues, start=1):
        poi = ET.SubElement(song, "Poi")
        poi.set("Name", build_cue_name(seg))
        poi.set("Pos", str(seg.start))
        poi.set("Num", str(i))
        poi.set("Type", "cue")

    # Re-indent to match VDJ's style (1 space for Song, 2 spaces for children)
    ET.indent(tree, space=" ")

    # Write back preserving VDJ's expected format:
    # - Double quotes in XML declaration
    # - CRLF line endings
    # - Indentation matching original file
    buf = BytesIO()
    tree.write(buf, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
    output = buf.getvalue().decode("utf-8")
    # Fix single quotes in XML declaration to double quotes
    output = re.sub(
        r"<\?xml version='1\.0' encoding='UTF-8'\?>",
        '<?xml version="1.0" encoding="UTF-8"?>',
        output,
    )
    # Normalize to CRLF line endings (VDJ uses CRLF on all platforms)
    output = output.replace("\r\n", "\n").replace("\n", "\r\n")
    db_path.write_bytes(output.encode("utf-8"))
    logger.info("Wrote %d cue points to VDJ database for %s", len(cues), filepath)
