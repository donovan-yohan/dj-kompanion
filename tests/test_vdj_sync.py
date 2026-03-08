"""Tests for server/vdj_sync.py — VDJ database sync from analysis sidecars."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from server.models import AnalysisResult, SegmentInfo
from server.track_db import get_track, init_db, mark_analyzed, upsert_track
from server.vdj_sync import is_vdj_running, sync_vdj


def _make_vdj_db(tmp_path: Path, filepaths: list[str]) -> Path:
    db_path = tmp_path / "database.xml"
    root = ET.Element("VirtualDJ_Database", Version="2026")
    for fp in filepaths:
        song = ET.SubElement(root, "Song", FilePath=fp)
        ET.SubElement(song, "Scan", Version="801", Bpm="0.468")
    tree = ET.ElementTree(root)
    tree.write(str(db_path), encoding="UTF-8", xml_declaration=True)
    return db_path


def _write_sidecar(path: str, bpm: float = 128.0) -> None:
    data = AnalysisResult(
        bpm=bpm,
        key="Am",
        key_camelot="8A",
        beats=[0.234],
        downbeats=[0.234],
        segments=[
            SegmentInfo(
                label="Drop 1 (16 bars)",
                original_label="chorus",
                start=60.5,
                end=90.5,
                bars=16,
            )
        ],
    ).model_dump()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data))


class TestIsVdjRunning:
    @patch("server.vdj_sync.subprocess.run")
    def test_not_running(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value.returncode = 1
        assert is_vdj_running() is False

    @patch("server.vdj_sync.subprocess.run")
    def test_running(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value.returncode = 0
        assert is_vdj_running() is True


class TestSyncVdj:
    def test_syncs_analyzed_tracks(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        analysis_dir = tmp_path / "analysis"
        vdj_path = _make_vdj_db(tmp_path, ["/music/song.m4a"])

        init_db(db_path)
        upsert_track(db_path, "/music/song.m4a")
        sidecar = str(analysis_dir / "song.meta.json")
        _write_sidecar(sidecar)
        mark_analyzed(db_path, "/music/song.m4a", sidecar)

        with patch("server.vdj_sync.is_vdj_running", return_value=False):
            result = sync_vdj(db_path, vdj_path, max_cues=8)

        assert result.synced == 1
        assert result.skipped == 0
        track = get_track(db_path, "/music/song.m4a")
        assert track is not None
        assert track.status == "synced"

    def test_refuses_if_vdj_running(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        vdj_path = tmp_path / "database.xml"
        init_db(db_path)

        with patch("server.vdj_sync.is_vdj_running", return_value=True):
            result = sync_vdj(db_path, vdj_path, max_cues=8)

        assert result.refused is True

    def test_skips_songs_not_in_vdj(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        analysis_dir = tmp_path / "analysis"
        vdj_path = _make_vdj_db(tmp_path, [])  # empty VDJ db

        init_db(db_path)
        upsert_track(db_path, "/music/song.m4a")
        sidecar = str(analysis_dir / "song.meta.json")
        _write_sidecar(sidecar)
        mark_analyzed(db_path, "/music/song.m4a", sidecar)

        with patch("server.vdj_sync.is_vdj_running", return_value=False):
            result = sync_vdj(db_path, vdj_path, max_cues=8)

        assert result.synced == 0
        assert result.skipped == 1
