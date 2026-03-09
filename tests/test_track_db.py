"""Tests for server/track_db.py — SQLite track status database."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.track_db import (
    get_pending_analysis,
    get_track,
    init_db,
    mark_analyzed,
    mark_analyzing,
    mark_failed,
    upsert_track,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestInitDb:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        assert db_path.exists()

    def test_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        init_db(db_path)  # should not raise


class TestUpsertTrack:
    def test_inserts_new_track(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/path/to/song.m4a")
        track = get_track(db_path, "/path/to/song.m4a")
        assert track is not None
        assert track.status == "downloaded"

    def test_resets_to_downloaded_on_re_upsert(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/path/to/song.m4a")
        mark_analyzing(db_path, "/path/to/song.m4a")
        upsert_track(db_path, "/path/to/song.m4a")
        track = get_track(db_path, "/path/to/song.m4a")
        assert track is not None
        assert track.status == "downloaded"


class TestStatusTransitions:
    def test_full_lifecycle(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/path/to/song.m4a")

        mark_analyzing(db_path, "/path/to/song.m4a")
        assert get_track(db_path, "/path/to/song.m4a").status == "analyzing"

        mark_analyzed(db_path, "/path/to/song.m4a", "/config/analysis/song.meta.json")
        track = get_track(db_path, "/path/to/song.m4a")
        assert track.status == "analyzed"
        assert track.analysis_path == "/config/analysis/song.meta.json"
        assert track.analyzed_at is not None

    def test_mark_failed(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/path/to/song.m4a")
        mark_failed(db_path, "/path/to/song.m4a", "connection timeout")
        track = get_track(db_path, "/path/to/song.m4a")
        assert track.status == "failed"
        assert track.error == "connection timeout"


class TestQueries:
    def test_get_pending_analysis(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/a.m4a")
        upsert_track(db_path, "/b.m4a")
        mark_analyzing(db_path, "/b.m4a")
        pending = get_pending_analysis(db_path)
        assert len(pending) == 1
        assert pending[0].filepath == "/a.m4a"
