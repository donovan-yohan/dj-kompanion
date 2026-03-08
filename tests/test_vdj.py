"""Tests for server/vdj.py — Virtual DJ database.xml writer."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from server.models import AnalysisResult, SegmentInfo
from server.vdj import (
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


def _make_db_with_song(tmp_path: Path, filepath: str = "/path/to/track.m4a") -> Path:
    """Create a VDJ database.xml with an existing Song element (as VDJ would write it)."""
    db_path = tmp_path / "database.xml"
    root = ET.Element("VirtualDJ_Database", Version="2026")
    song = ET.SubElement(root, "Song", FilePath=filepath, FileSize="10613834")
    ET.SubElement(song, "Tags", Author="Artist", Title="Title", Genre="Genre")
    ET.SubElement(song, "Infos", SongLength="195.0", LastModified="1772998059")
    ET.SubElement(song, "Scan", Version="801", Bpm="0.468753", Key="Am", Volume="1.3")
    ET.SubElement(song, "Poi", Pos="-1.339887", Type="beatgrid")
    ET.SubElement(song, "Poi", Pos="0.058667", Type="automix", Point="realStart")
    ET.SubElement(song, "Poi", Pos="194.978667", Type="automix", Point="realEnd")
    tree = ET.ElementTree(root)
    tree.write(str(db_path), encoding="UTF-8", xml_declaration=True)
    return db_path


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        bpm=128.0,
        key="Am",
        key_camelot="8A",
        beats=[0.234, 0.703, 1.172, 1.641],
        downbeats=[0.234, 1.172],
        segments=[
            SegmentInfo(
                label="Intro (32 bars)", original_label="intro", start=0.234, end=60.5, bars=32
            ),
            SegmentInfo(
                label="Drop 1 (16 bars)", original_label="chorus", start=60.5, end=90.5, bars=16
            ),
            SegmentInfo(
                label="Breakdown (8 bars)", original_label="break", start=90.5, end=105.5, bars=8
            ),
            SegmentInfo(
                label="Drop 2 (16 bars)", original_label="chorus", start=105.5, end=135.5, bars=16
            ),
            SegmentInfo(
                label="Outro (16 bars)", original_label="outro", start=135.5, end=165.5, bars=16
            ),
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
        assert all("Drop" in label for label in labels)


class TestWriteToVdjDatabase:
    def test_skips_unknown_song(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        written = write_to_vdj_database(db_path, "/path/to/track.m4a", result)
        assert written is False

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is None  # should not create new Song entries

    def test_writes_cue_pois(self, tmp_path: Path) -> None:
        db_path = _make_db_with_song(tmp_path)
        result = _sample_result()
        written = write_to_vdj_database(db_path, "/path/to/track.m4a", result, max_cues=8)
        assert written is True

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        cues = [p for p in song.findall("Poi") if p.get("Type") == "cue"]
        assert len(cues) == 5  # all 5 segments fit within 8

    def test_preserves_existing_vdj_elements(self, tmp_path: Path) -> None:
        db_path = _make_db_with_song(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        # VDJ's own elements should still be present
        assert song.find("Tags") is not None
        assert song.find("Infos") is not None
        assert song.find("Scan") is not None
        assert song.find(".//Poi[@Type='beatgrid']") is not None
        assert song.find(".//Poi[@Type='automix']") is not None

    def test_replaces_cues_on_update(self, tmp_path: Path) -> None:
        db_path = _make_db_with_song(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result, max_cues=3)

        # Write again — should replace cues, not double them
        write_to_vdj_database(db_path, "/path/to/track.m4a", result, max_cues=3)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        cues = [p for p in song.findall("Poi") if p.get("Type") == "cue"]
        assert len(cues) == 3  # not 6

    def test_does_not_duplicate_song(self, tmp_path: Path) -> None:
        db_path = _make_db_with_song(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        songs = [s for s in tree.getroot().findall("Song") if s.get("FilePath") == "/path/to/track.m4a"]
        assert len(songs) == 1

    def test_skips_if_db_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nonexistent" / "database.xml"
        result = _sample_result()
        # Should not raise
        written = write_to_vdj_database(db_path, "/path/to/track.m4a", result)
        assert written is False

    def test_handles_filepath_with_quotes_and_apostrophes(self, tmp_path: Path) -> None:
        special_path = "/path/with \"quote\" and 'apostrophe'.m4a"
        db_path = _make_db_with_song(tmp_path, filepath=special_path)
        result = _sample_result()
        write_to_vdj_database(db_path, special_path, result)

        tree = ET.parse(db_path)
        root = tree.getroot()
        songs = root.findall(".//Song")
        matching = [song for song in songs if song.get("FilePath") == special_path]
        assert len(matching) == 1
        cues = [p for p in matching[0].findall("Poi") if p.get("Type") == "cue"]
        assert len(cues) > 0
