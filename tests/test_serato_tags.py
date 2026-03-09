"""Tests for server/serato_tags.py — Serato GEOB cue point writer."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from server.models import AnalysisResult, SegmentInfo
from server.serato_tags import _build_cue_name, write_serato_cues

if TYPE_CHECKING:
    from pathlib import Path

HAS_FFMPEG = shutil.which("ffmpeg") is not None

SAMPLE_SEGMENTS = [
    SegmentInfo(label="Intro", original_label="intro", start=0.0, end=8.0, bars=8),
    SegmentInfo(label="Drop", original_label="drop", start=8.0, end=24.0, bars=16),
    SegmentInfo(label="Verse", original_label="verse", start=24.0, end=48.0, bars=24),
]

SAMPLE_RESULT = AnalysisResult(
    bpm=128.0,
    key="Am",
    key_camelot="8A",
    beats=[float(i) * 0.46875 for i in range(100)],
    downbeats=[float(i) * 1.875 for i in range(25)],
    segments=SAMPLE_SEGMENTS,
)


def make_silent_mp3(path: Path) -> None:
    """Create a short silent MP3 via ffmpeg; skip the test if unavailable."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not available")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        "0.5",
        str(path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg couldn't create MP3: {exc.stderr.decode()[:200]}")


# ─── _build_cue_name ────────────────────────────────────────────────────────


class TestBuildCueName:
    def test_singular_bar(self) -> None:
        assert _build_cue_name("Intro", 1) == "Intro (1 bar)"

    def test_plural_bars(self) -> None:
        assert _build_cue_name("Drop", 16) == "Drop (16 bars)"


# ─── Non-MP3 returns False ──────────────────────────────────────────────────


class TestNonMp3:
    def test_flac_returns_false(self, tmp_path: Path) -> None:
        fp = tmp_path / "audio.flac"
        fp.write_bytes(b"fake")
        assert write_serato_cues(fp, SAMPLE_RESULT) is False

    def test_m4a_returns_false(self, tmp_path: Path) -> None:
        fp = tmp_path / "audio.m4a"
        fp.write_bytes(b"fake")
        assert write_serato_cues(fp, SAMPLE_RESULT) is False

    def test_wav_returns_false(self, tmp_path: Path) -> None:
        fp = tmp_path / "audio.wav"
        fp.write_bytes(b"fake")
        assert write_serato_cues(fp, SAMPLE_RESULT) is False


# ─── Writes cues to real MP3 ────────────────────────────────────────────────


class TestWriteCues:
    def test_writes_correct_number_of_cues(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent_mp3(fp)

        assert write_serato_cues(fp, SAMPLE_RESULT) is True

        from serato_tools.track_cues_v2 import TrackCuesV2

        tags = TrackCuesV2(str(fp))
        cue_entries = [e for e in tags.entries if isinstance(e, TrackCuesV2.CueEntry)]
        assert len(cue_entries) == 3

    def test_cue_positions_match_segments(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent_mp3(fp)

        write_serato_cues(fp, SAMPLE_RESULT)

        from serato_tools.track_cues_v2 import TrackCuesV2

        tags = TrackCuesV2(str(fp))
        cue_entries = [e for e in tags.entries if isinstance(e, TrackCuesV2.CueEntry)]
        assert cue_entries[0].position == 0
        assert cue_entries[1].position == 8000
        assert cue_entries[2].position == 24000

    def test_cue_names_include_bar_count(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent_mp3(fp)

        write_serato_cues(fp, SAMPLE_RESULT)

        from serato_tools.track_cues_v2 import TrackCuesV2

        tags = TrackCuesV2(str(fp))
        cue_entries = [e for e in tags.entries if isinstance(e, TrackCuesV2.CueEntry)]
        assert cue_entries[0].name == "Intro (8 bars)"
        assert cue_entries[1].name == "Drop (16 bars)"
        assert cue_entries[2].name == "Verse (24 bars)"

    def test_empty_segments_returns_false(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent_mp3(fp)

        empty_result = AnalysisResult(
            bpm=128.0,
            key="Am",
            key_camelot="8A",
            beats=[],
            downbeats=[],
            segments=[],
        )
        assert write_serato_cues(fp, empty_result) is False


# ─── Graceful failure ────────────────────────────────────────────────────────


class TestGracefulFailure:
    def test_returns_false_on_exception(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        fp.write_bytes(b"not a real mp3")

        assert write_serato_cues(fp, SAMPLE_RESULT) is False

    def test_returns_false_when_serato_tools_raises(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent_mp3(fp)

        with patch(
            "server.serato_tags.TrackCuesV2",
            side_effect=RuntimeError("serato-tools exploded"),
        ):
            assert write_serato_cues(fp, SAMPLE_RESULT) is False
