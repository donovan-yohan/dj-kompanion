"""Tests for server/key_detect.py — musical key detection + Camelot conversion."""

from __future__ import annotations

import pytest

from server.key_detect import to_camelot, to_standard_notation


class TestToStandardNotation:
    def test_major(self) -> None:
        assert to_standard_notation("C", "major") == "C"

    def test_minor(self) -> None:
        assert to_standard_notation("A", "minor") == "Am"

    def test_sharp(self) -> None:
        assert to_standard_notation("F#", "minor") == "F#m"


class TestToCamelot:
    def test_a_minor(self) -> None:
        assert to_camelot("A", "minor") == "8A"

    def test_c_major(self) -> None:
        assert to_camelot("C", "major") == "8B"

    def test_f_sharp_minor(self) -> None:
        assert to_camelot("F#", "minor") == "11A"

    def test_b_flat_major(self) -> None:
        assert to_camelot("Bb", "major") == "6B"

    def test_unknown_key_returns_empty(self) -> None:
        assert to_camelot("X", "major") == ""

    @pytest.mark.parametrize(
        ("key", "scale", "expected"),
        [
            ("B", "major", "1B"),
            ("Ab", "minor", "1A"),
            ("E", "major", "12B"),
            ("Db", "minor", "12A"),
        ],
    )
    def test_camelot_endpoints(self, key: str, scale: str, expected: str) -> None:
        assert to_camelot(key, scale) == expected
