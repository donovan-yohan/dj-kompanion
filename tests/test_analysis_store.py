# tests/test_analysis_store.py
"""Tests for server/analysis_store.py — analysis sidecar JSON writer/reader."""

from __future__ import annotations

from pathlib import Path

from server.analysis_store import load_analysis, save_analysis, sidecar_path
from server.models import AnalysisResult, SegmentInfo


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        bpm=128.0,
        key="Am",
        key_camelot="8A",
        beats=[0.234, 0.703],
        downbeats=[0.234, 1.172],
        segments=[
            SegmentInfo(label="Drop 1 (16 bars)", original_label="chorus", start=60.5, end=90.5, bars=16),
        ],
    )


class TestSidecarPath:
    def test_contains_stem_and_hash(self) -> None:
        p = sidecar_path(Path("/config/analysis"), Path("/music/Artist - Title.m4a"))
        assert p.parent == Path("/config/analysis")
        assert "Artist - Title" in p.stem
        assert p.suffix == ".json"

    def test_collision_suffix(self) -> None:
        base = Path("/config/analysis")
        audio = Path("/music/Artist - Title.m4a")
        p1 = sidecar_path(base, audio)
        # Same stem but different parent — should get hash suffix
        audio2 = Path("/other/Artist - Title.m4a")
        p2 = sidecar_path(base, audio2)
        assert p1 != p2
        assert "Artist - Title" in p2.stem


class TestSaveAndLoad:
    def test_round_trip(self, tmp_path: Path) -> None:
        analysis_dir = tmp_path / "analysis"
        analysis_dir.mkdir()
        audio_path = Path("/music/Song.m4a")
        result = _sample_result()
        out_path = save_analysis(analysis_dir, audio_path, result)
        assert out_path.exists()
        loaded = load_analysis(out_path)
        assert loaded.bpm == result.bpm
        assert loaded.key == result.key
        assert len(loaded.segments) == len(result.segments)

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        loaded = load_analysis(tmp_path / "nonexistent.meta.json")
        assert loaded is None
