"""Musical key detection and Camelot notation conversion."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_CAMELOT_MAJOR: dict[str, str] = {
    "B": "1B",
    "F#": "2B",
    "Db": "3B",
    "Ab": "4B",
    "Eb": "5B",
    "Bb": "6B",
    "F": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B",
}

_CAMELOT_MINOR: dict[str, str] = {
    "Ab": "1A",
    "Eb": "2A",
    "Bb": "3A",
    "F": "4A",
    "C": "5A",
    "G": "6A",
    "D": "7A",
    "A": "8A",
    "E": "9A",
    "B": "10A",
    "F#": "11A",
    "Db": "12A",
}


def to_standard_notation(key: str, scale: str) -> str:
    """Convert key + scale to standard DJ notation (e.g., 'Am', 'F#m', 'C')."""
    if scale == "minor":
        return f"{key}m"
    return key


def to_camelot(key: str, scale: str) -> str:
    """Convert key + scale to Camelot wheel notation (e.g., '8A', '11B')."""
    table = _CAMELOT_MINOR if scale == "minor" else _CAMELOT_MAJOR
    return table.get(key, "")


def _detect_key_sync(filepath: Path) -> tuple[str, str, float]:
    """Run essentia KeyExtractor. Returns (key, scale, strength)."""
    import essentia.standard as es  # type: ignore[import-untyped]

    audio: Any = es.MonoLoader(filename=str(filepath))()
    key_extractor: Any = es.KeyExtractor(profileType="bgate")
    key: str
    scale: str
    strength: float
    key, scale, strength = key_extractor(audio)
    return key, scale, float(strength)


async def detect_key(filepath: Path) -> tuple[str, str, str, float]:
    """Detect musical key of an audio file.

    Returns (standard_notation, camelot_notation, scale, strength).
    Example: ("Am", "8A", "minor", 0.87)
    """
    key, scale, strength = await asyncio.to_thread(_detect_key_sync, filepath)
    standard = to_standard_notation(key, scale)
    camelot = to_camelot(key, scale)
    logger.info("Key detected: %s (Camelot: %s, strength: %.3f)", standard, camelot, strength)
    return standard, camelot, scale, strength
