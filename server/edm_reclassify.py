"""EDM reclassification of allin1 segment labels using stem energy analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# RMS energy thresholds for classifying high-energy sections
_HIGH_DRUMS_THRESHOLD = 0.5
_HIGH_BASS_THRESHOLD = 0.4

# Type alias for stem energies: {(start, end): {"drums": float, "bass": float}}
StemEnergies = dict[tuple[float, float], dict[str, float]]


@dataclass
class RawSegment:
    """A segment as returned by allin1."""

    label: str
    start: float
    end: float


@dataclass
class ClassifiedSegment:
    """A segment with EDM label and original label preserved."""

    label: str
    original_label: str
    start: float
    end: float


def _is_high_energy(
    seg: RawSegment,
    stem_energies: StemEnergies | None,
) -> bool:
    """Check if a segment has high drum + bass energy (indicating a drop)."""
    if stem_energies is None:
        return False
    energy = stem_energies.get((seg.start, seg.end))
    if energy is None:
        return False
    return (
        energy.get("drums", 0.0) >= _HIGH_DRUMS_THRESHOLD
        and energy.get("bass", 0.0) >= _HIGH_BASS_THRESHOLD
    )


def _classify_segment(
    seg: RawSegment,
    next_seg: RawSegment | None,
    stem_energies: StemEnergies | None,
) -> str | None:
    """Map a single allin1 label to an EDM label. Returns None to filter out."""
    label = seg.label

    if label in ("start", "end"):
        return None

    direct_map: dict[str, str] = {
        "intro": "Intro",
        "outro": "Outro",
        "verse": "Verse",
        "bridge": "Bridge",
        "inst": "Instrumental",
        "solo": "Solo",
    }

    if label in direct_map:
        return direct_map[label]

    if label == "chorus":
        if _is_high_energy(seg, stem_energies):
            return "Drop"
        return "Chorus"

    if label == "break":
        # If next segment is a high-energy chorus (drop), this break is a buildup
        if (
            next_seg is not None
            and next_seg.label == "chorus"
            and _is_high_energy(next_seg, stem_energies)
        ):
            return "Buildup"
        return "Breakdown"

    # Unknown label — capitalize and pass through
    return label.capitalize()


def _number_duplicates(segments: list[ClassifiedSegment]) -> None:
    """Add numbering to repeated labels (e.g., Drop -> Drop 1, Drop 2)."""
    label_counts: dict[str, int] = {}
    for seg in segments:
        label_counts[seg.label] = label_counts.get(seg.label, 0) + 1

    labels_needing_numbers = {label for label, count in label_counts.items() if count > 1}

    counters: dict[str, int] = {}
    for seg in segments:
        if seg.label in labels_needing_numbers:
            counters[seg.label] = counters.get(seg.label, 0) + 1
            seg.label = f"{seg.label} {counters[seg.label]}"


def reclassify_labels(
    segments: list[RawSegment],
    stem_energies: StemEnergies | None,
) -> list[ClassifiedSegment]:
    """Reclassify allin1 segments into EDM-appropriate labels.

    Uses stem energy data (if available) to distinguish drops from choruses
    and buildups from breakdowns.
    """
    classified: list[ClassifiedSegment] = []

    for i, seg in enumerate(segments):
        next_seg = segments[i + 1] if i + 1 < len(segments) else None
        edm_label = _classify_segment(seg, next_seg, stem_energies)
        if edm_label is None:
            continue
        classified.append(
            ClassifiedSegment(
                label=edm_label,
                original_label=seg.label,
                start=seg.start,
                end=seg.end,
            )
        )

    _number_duplicates(classified)
    return classified
