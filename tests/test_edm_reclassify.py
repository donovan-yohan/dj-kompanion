"""Tests for _merge_consecutive in analyzer.edm_reclassify."""

from __future__ import annotations

from analyzer.edm_reclassify import ClassifiedSegment, _merge_consecutive


def _seg(label: str, start: float, end: float) -> ClassifiedSegment:
    return ClassifiedSegment(label=label, original_label=label.lower(), start=start, end=end)


class TestMergeConsecutive:
    def test_consecutive_same_type_merged(self) -> None:
        segments = [_seg("Verse", 0.0, 10.0), _seg("Verse", 10.0, 20.0), _seg("Verse", 20.0, 30.0)]
        result = _merge_consecutive(segments)
        assert len(result) == 1
        assert result[0].label == "Verse"
        assert result[0].original_label == "verse"
        assert result[0].start == 0.0
        assert result[0].end == 30.0

    def test_different_types_preserved(self) -> None:
        segments = [_seg("Intro", 0.0, 10.0), _seg("Verse", 10.0, 20.0), _seg("Chorus", 20.0, 30.0)]
        result = _merge_consecutive(segments)
        assert len(result) == 3
        assert [s.label for s in result] == ["Intro", "Verse", "Chorus"]

    def test_non_consecutive_same_type_kept_separate(self) -> None:
        segments = [_seg("Drop", 0.0, 10.0), _seg("Breakdown", 10.0, 20.0), _seg("Drop", 20.0, 30.0)]
        result = _merge_consecutive(segments)
        assert len(result) == 3
        assert [s.label for s in result] == ["Drop", "Breakdown", "Drop"]

    def test_empty_input(self) -> None:
        assert _merge_consecutive([]) == []

    def test_single_segment(self) -> None:
        segments = [_seg("Intro", 0.0, 10.0)]
        result = _merge_consecutive(segments)
        assert len(result) == 1
        assert result[0].label == "Intro"
        assert result[0].start == 0.0
        assert result[0].end == 10.0
