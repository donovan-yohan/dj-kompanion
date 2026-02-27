"""Tests for server/analyzer.py — analysis pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.analyzer import analyze_audio
from server.models import AnalysisResult


@dataclass
class MockAllin1Segment:
    label: str
    start: float
    end: float


@dataclass
class MockAllin1Result:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    beat_positions: list[int]
    segments: list[MockAllin1Segment]


def _mock_allin1_result() -> MockAllin1Result:
    """Simulate allin1.analyze() output for a 128 BPM track."""
    return MockAllin1Result(
        bpm=128.0,
        beats=[0.0 + i * 0.46875 for i in range(64)],
        downbeats=[0.0 + i * 1.875 for i in range(16)],
        beat_positions=[((i % 4) + 1) for i in range(64)],
        segments=[
            MockAllin1Segment(label="start", start=0.0, end=0.0),
            MockAllin1Segment(label="intro", start=0.0, end=7.5),
            MockAllin1Segment(label="chorus", start=7.5, end=15.0),
            MockAllin1Segment(label="break", start=15.0, end=18.75),
            MockAllin1Segment(label="chorus", start=18.75, end=26.25),
            MockAllin1Segment(label="outro", start=26.25, end=30.0),
            MockAllin1Segment(label="end", start=30.0, end=30.0),
        ],
    )


@pytest.fixture
def mock_allin1() -> Any:
    with patch("server.analyzer.allin1") as mock:
        mock.analyze.return_value = _mock_allin1_result()
        yield mock


@pytest.fixture
def mock_key_detect() -> Any:
    with patch("server.analyzer.detect_key", new_callable=AsyncMock) as mock:
        mock.return_value = ("Am", "8A", "minor", 0.87)
        yield mock


@pytest.fixture
def mock_stem_energies() -> Any:
    with patch("server.analyzer._compute_stem_energies") as mock:
        # Return high energy for chorus segments, low for others
        mock.return_value = {
            (7.5, 15.0): {"drums": 0.8, "bass": 0.7},
            (18.75, 26.25): {"drums": 0.8, "bass": 0.7},
        }
        yield mock


async def test_analyze_returns_result(
    tmp_path: Path, mock_allin1: Any, mock_key_detect: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    result = await analyze_audio(filepath)
    assert isinstance(result, AnalysisResult)
    assert result.bpm == 128.0
    assert result.key == "Am"
    assert result.key_camelot == "8A"


async def test_segments_reclassified_to_edm(
    tmp_path: Path, mock_allin1: Any, mock_key_detect: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    result = await analyze_audio(filepath)
    labels = [s.label for s in result.segments]
    assert "Intro" in labels[0]
    # Chorus with high energy should become Drop
    assert any("Drop" in l for l in labels)


async def test_segments_have_bar_counts(
    tmp_path: Path, mock_allin1: Any, mock_key_detect: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    result = await analyze_audio(filepath)
    for seg in result.segments:
        assert seg.bars >= 1


async def test_allin1_failure_returns_none(tmp_path: Path, mock_key_detect: Any) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    with patch("server.analyzer.allin1") as mock:
        mock.analyze.side_effect = RuntimeError("NATTEN crash")
        result = await analyze_audio(filepath)
    assert result is None


async def test_key_detect_failure_uses_unknown(
    tmp_path: Path, mock_allin1: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    with patch("server.analyzer.detect_key", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("essentia error")
        result = await analyze_audio(filepath)
    assert result is not None
    assert result.key == ""
    assert result.key_camelot == ""
