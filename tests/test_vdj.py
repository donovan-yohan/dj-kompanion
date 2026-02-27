"""Tests for server/vdj.py — Virtual DJ database.xml writer."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from server.models import AnalysisResult, SegmentInfo
from server.vdj import (
    CUE_PRIORITY,
    bpm_to_seconds_per_beat,
    build_cue_name,
    prioritize_cues,
    write_to_vdj_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal VDJ database.xml."""
    db_path = tmp_path / "database.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<VirtualDJ_Database Version="8.2">\n'
        "</VirtualDJ_Database>\n"
    )
    return db_path


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        bpm=128.0,
        key="Am",
        key_camelot="8A",
        beats=[0.234, 0.703, 1.172, 1.641],
        downbeats=[0.234, 1.172],
        segments=[
            SegmentInfo(label="Intro (32 bars)", original_label="intro", start=0.234, end=60.5, bars=32),
            SegmentInfo(label="Drop 1 (16 bars)", original_label="chorus", start=60.5, end=90.5, bars=16),
            SegmentInfo(label="Breakdown (8 bars)", original_label="break", start=90.5, end=105.5, bars=8),
            SegmentInfo(label="Drop 2 (16 bars)", original_label="chorus", start=105.5, end=135.5, bars=16),
            SegmentInfo(label="Outro (16 bars)", original_label="outro", start=135.5, end=165.5, bars=16),
        ],
    )


class TestBpmConversion:
    def test_128_bpm(self) -> None:
        assert bpm_to_seconds_per_beat(128.0) == 60.0 / 128.0

    def test_140_bpm(self) -> None:
        result = bpm_to_seconds_per_beat(140.0)
        assert abs(result - 60.0 / 140.0) < 1e-10


class TestBuildCueName:
    def test_with_bars(self) -> None:
        seg = SegmentInfo(label="Drop 1", original_label="chorus", start=60.0, end=90.0, bars=16)
        assert build_cue_name(seg) == "Drop 1 (16 bars)"

    def test_single_bar(self) -> None:
        seg = SegmentInfo(label="Intro", original_label="intro", start=0.0, end=2.0, bars=1)
        assert build_cue_name(seg) == "Intro (1 bar)"


class TestPrioritizeCues:
    def test_respects_max_cues(self) -> None:
        result = _sample_result()
        cues = prioritize_cues(result.segments, max_cues=3)
        assert len(cues) == 3

    def test_drops_first(self) -> None:
        result = _sample_result()
        cues = prioritize_cues(result.segments, max_cues=2)
        # Both drops should come first
        labels = [c.label for c in cues]
        assert all("Drop" in l for l in labels)


class TestWriteToVdjDatabase:
    def test_creates_song_element(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None

    def test_writes_scan_bpm(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        scan = song.find("Scan")
        assert scan is not None
        assert float(scan.get("Bpm", "0")) == 60.0 / 128.0

    def test_writes_scan_key(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        scan = song.find("Scan")
        assert scan is not None
        assert scan.get("Key") == "Am"

    def test_writes_beatgrid_poi(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        beatgrid = song.find(".//Poi[@Type='beatgrid']")
        assert beatgrid is not None
        assert float(beatgrid.get("Pos", "0")) == 0.234

    def test_writes_cue_pois(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result, max_cues=8)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        cues = [p for p in song.findall("Poi") if p.get("Type") is None and p.get("Num")]
        assert len(cues) == 5  # all 5 segments fit within 8

    def test_skips_if_db_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nonexistent" / "database.xml"
        result = _sample_result()
        # Should not raise
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

    def test_updates_existing_song(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)
        # Write again with different BPM
        result2 = _sample_result()
        result2.bpm = 140.0
        write_to_vdj_database(db_path, "/path/to/track.m4a", result2)

        tree = ET.parse(db_path)
        songs = tree.getroot().findall(".//Song[@FilePath='/path/to/track.m4a']")
        assert len(songs) == 1  # no duplicate
        scan = songs[0].find("Scan")
        assert scan is not None
        assert abs(float(scan.get("Bpm", "0")) - 60.0 / 140.0) < 1e-10
