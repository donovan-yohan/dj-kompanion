from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models import AnalysisResult, AnalyzeRequest, AnalyzeResponse, SegmentInfo


class TestSegmentInfo:
    def test_valid(self) -> None:
        seg = SegmentInfo(label="verse", original_label="verse", start=0.0, end=4.0, bars=4)
        assert seg.label == "verse"
        assert seg.original_label == "verse"
        assert seg.start == 0.0
        assert seg.end == 4.0
        assert seg.bars == 4

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValidationError):
            SegmentInfo(label="verse", original_label="verse", start=0.0, end=4.0)  # type: ignore[call-arg]

    def test_float_times(self) -> None:
        seg = SegmentInfo(label="chorus", original_label="Chorus", start=1.5, end=9.25, bars=8)
        assert seg.start == 1.5
        assert seg.end == 9.25


class TestAnalysisResult:
    def _make(self, **kwargs: object) -> AnalysisResult:
        defaults: dict[str, object] = {
            "bpm": 128.0,
            "key": "Am",
            "key_camelot": "8A",
            "beats": [0.0, 0.469, 0.938],
            "downbeats": [0.0, 1.875],
            "segments": [],
        }
        defaults.update(kwargs)
        return AnalysisResult(**defaults)  # type: ignore[arg-type]

    def test_valid_minimal(self) -> None:
        result = self._make()
        assert result.bpm == 128.0
        assert result.key == "Am"
        assert result.key_camelot == "8A"
        assert result.beats == [0.0, 0.469, 0.938]
        assert result.downbeats == [0.0, 1.875]
        assert result.segments == []
        assert result.vdj_written is False  # default

    def test_vdj_written_default_false(self) -> None:
        result = self._make()
        assert result.vdj_written is False

    def test_vdj_written_can_be_true(self) -> None:
        result = self._make(vdj_written=True)
        assert result.vdj_written is True

    def test_with_segments(self) -> None:
        seg = SegmentInfo(label="intro", original_label="intro", start=0.0, end=8.0, bars=4)
        result = self._make(segments=[seg])
        assert len(result.segments) == 1
        assert result.segments[0].label == "intro"

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisResult(bpm=128.0, key="Am")  # type: ignore[call-arg]


class TestAnalyzeRequest:
    def test_valid(self) -> None:
        req = AnalyzeRequest(filepath="/tmp/track.mp3")
        assert req.filepath == "/tmp/track.mp3"

    def test_missing_filepath(self) -> None:
        with pytest.raises(ValidationError):
            AnalyzeRequest()  # type: ignore[call-arg]


class TestAnalyzeResponse:
    def test_valid(self) -> None:
        analysis = AnalysisResult(
            bpm=140.0,
            key="Dm",
            key_camelot="7A",
            beats=[0.0, 0.428],
            downbeats=[0.0],
            segments=[],
        )
        resp = AnalyzeResponse(status="ok", analysis=analysis)
        assert resp.status == "ok"
        assert resp.analysis.bpm == 140.0

    def test_missing_analysis(self) -> None:
        with pytest.raises(ValidationError):
            AnalyzeResponse(status="ok")  # type: ignore[call-arg]
