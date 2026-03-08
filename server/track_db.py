"""SQLite track status database for the analysis pipeline."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class TrackRow:
    id: int
    filepath: str
    analysis_path: str | None
    status: str
    error: str | None
    analyzed_at: str | None
    synced_at: str | None
    created_at: str


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE NOT NULL,
    analysis_path TEXT,
    status TEXT NOT NULL DEFAULT 'downloaded',
    error TEXT,
    analyzed_at TEXT,
    synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_track(
    row: tuple[int, str, str | None, str, str | None, str | None, str | None, str],
) -> TrackRow:
    return TrackRow(
        id=row[0],
        filepath=row[1],
        analysis_path=row[2],
        status=row[3],
        error=row[4],
        analyzed_at=row[5],
        synced_at=row[6],
        created_at=row[7],
    )


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(_CREATE_TABLE)


def upsert_track(db_path: Path, filepath: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO tracks (filepath, status, error, analysis_path, analyzed_at, synced_at, created_at)
               VALUES (?, 'downloaded', NULL, NULL, NULL, NULL, ?)
               ON CONFLICT(filepath) DO UPDATE SET
                 status = 'downloaded',
                 error = NULL,
                 analysis_path = NULL,
                 analyzed_at = NULL,
                 synced_at = NULL""",
            (filepath, _now()),
        )


def get_track(db_path: Path, filepath: str) -> TrackRow | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tracks WHERE filepath = ?", (filepath,)
        ).fetchone()
    return _row_to_track(row) if row else None


def mark_analyzing(db_path: Path, filepath: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'analyzing', error = NULL WHERE filepath = ?",
            (filepath,),
        )


def mark_analyzed(db_path: Path, filepath: str, analysis_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'analyzed', analysis_path = ?, analyzed_at = ?, error = NULL WHERE filepath = ?",
            (analysis_path, _now(), filepath),
        )


def mark_synced(db_path: Path, filepath: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'synced', synced_at = ? WHERE filepath = ?",
            (_now(), filepath),
        )


def mark_failed(db_path: Path, filepath: str, error: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'failed', error = ? WHERE filepath = ?",
            (error, filepath),
        )


def get_unsynced(db_path: Path) -> list[TrackRow]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tracks WHERE status = 'analyzed'"
        ).fetchall()
    return [_row_to_track(r) for r in rows]


def get_all_tracks(db_path: Path) -> list[TrackRow]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tracks ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_track(r) for r in rows]


def get_pending_analysis(db_path: Path) -> list[TrackRow]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM tracks WHERE status = 'downloaded'"
        ).fetchall()
    return [_row_to_track(r) for r in rows]
