"""Tests for server/beat_utils.py — beat-snapping and bar-counting."""

from __future__ import annotations

from server.beat_utils import count_bars, snap_to_downbeat


class TestSnapToDownbeat:
    def test_exact_match(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        assert snap_to_downbeat(1.875, downbeats) == 1.875

    def test_snaps_to_nearest(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        assert snap_to_downbeat(1.9, downbeats) == 1.875

    def test_snaps_forward(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        assert snap_to_downbeat(3.6, downbeats) == 3.75

    def test_empty_downbeats_returns_original(self) -> None:
        assert snap_to_downbeat(5.0, []) == 5.0

    def test_single_downbeat(self) -> None:
        assert snap_to_downbeat(2.0, [0.0]) == 0.0


class TestCountBars:
    def test_counts_downbeats_in_range(self) -> None:
        # 4 downbeats within [0, 7.5) at BPM=128 (1.875s per bar)
        downbeats = [0.0, 1.875, 3.75, 5.625, 7.5]
        assert count_bars(0.0, 7.5, downbeats) == 4

    def test_exclusive_end(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        # end=3.75 excludes the downbeat at 3.75
        assert count_bars(0.0, 3.75, downbeats) == 2

    def test_empty_range_returns_zero(self) -> None:
        downbeats = [0.0, 1.875, 3.75]
        assert count_bars(10.0, 20.0, downbeats) == 0

    def test_minimum_one_bar_when_segment_exists(self) -> None:
        # Even if no downbeats land inside, if the segment spans time, return at least 1
        downbeats = [0.0, 10.0]
        assert count_bars(3.0, 7.0, downbeats) == 1

    def test_empty_downbeats(self) -> None:
        assert count_bars(0.0, 10.0, []) == 1
