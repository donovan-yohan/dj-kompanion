# Decoupled Analysis & VDJ Sync

> **Status**: Active | **Created**: 2026-03-08 | **Last Updated**: 2026-03-08
> **Design Doc**: `docs/design-docs/2026-03-08-decoupled-analysis-vdj-sync-design.md`
> **For Claude:** Use /harness:orchestrate to execute this plan.

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-03-08 | Design | Store analysis as sidecar .meta.json, not in database.xml | VDJ doesn't support external DB modification; prevents corruption |
| 2026-03-08 | Design | SQLite for lean status tracking | Minimal state machine: downloaded → analyzing → analyzed → synced |
| 2026-03-08 | Design | VDJ sync as separate manual step | VDJ only reads DB on startup; sync must happen when VDJ is closed |
| 2026-03-08 | Design | Safety check for running VDJ process | Refuse to write if VDJ is running to prevent corruption |
| 2026-03-08 | Design | Sidecar files in ~/.config, not next to audio | Keep music folder clean; VDJ browser won't see .json files |
| 2026-03-08 | Design | sync_vdj() works without server running | CLI use case: sync when server is off, VDJ is closed |

## Progress

- [ ] Task 1: SQLite track database module
- [ ] Task 2: Analysis sidecar writer
- [ ] Task 3: Refactor analyzer.py to use track_db + sidecar
- [ ] Task 4: VDJ sync module
- [ ] Task 5: New API endpoints (sync-vdj, tracks, reanalyze)
- [ ] Task 6: Refactor download endpoint for fire-and-forget analysis
- [ ] Task 7: Extension — sync button + track status display
- [ ] Task 8: Remove old direct-VDJ-write codepath

## Surprises & Discoveries

_None yet — updated during execution by /harness:orchestrate._

## Plan Drift

_None yet — updated when tasks deviate from plan during execution._

---

### Task 1: SQLite track database module

**Files:**
- Create: `server/track_db.py`
- Create: `tests/test_track_db.py`

**Step 1: Write the failing tests**

```python
# tests/test_track_db.py
"""Tests for server/track_db.py — SQLite track status database."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.track_db import (
    TrackRow,
    get_pending_analysis,
    get_track,
    get_unsynced,
    init_db,
    mark_analyzed,
    mark_analyzing,
    mark_failed,
    mark_synced,
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

        mark_synced(db_path, "/path/to/song.m4a")
        track = get_track(db_path, "/path/to/song.m4a")
        assert track.status == "synced"
        assert track.synced_at is not None

    def test_mark_failed(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/path/to/song.m4a")
        mark_failed(db_path, "/path/to/song.m4a", "connection timeout")
        track = get_track(db_path, "/path/to/song.m4a")
        assert track.status == "failed"
        assert track.error == "connection timeout"


class TestQueries:
    def test_get_unsynced(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/a.m4a")
        upsert_track(db_path, "/b.m4a")
        upsert_track(db_path, "/c.m4a")
        mark_analyzed(db_path, "/a.m4a", "/analysis/a.meta.json")
        mark_analyzed(db_path, "/b.m4a", "/analysis/b.meta.json")
        # /c.m4a stays as "downloaded"
        unsynced = get_unsynced(db_path)
        assert len(unsynced) == 2
        assert {t.filepath for t in unsynced} == {"/a.m4a", "/b.m4a"}

    def test_get_pending_analysis(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tracks.db"
        init_db(db_path)
        upsert_track(db_path, "/a.m4a")
        upsert_track(db_path, "/b.m4a")
        mark_analyzing(db_path, "/b.m4a")
        pending = get_pending_analysis(db_path)
        assert len(pending) == 1
        assert pending[0].filepath == "/a.m4a"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_track_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'server.track_db'`

**Step 3: Write the implementation**

```python
# server/track_db.py
"""SQLite track status database for the analysis pipeline."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
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
    return datetime.now(timezone.utc).isoformat()


def _row_to_track(row: tuple[int, str, str | None, str, str | None, str | None, str | None, str]) -> TrackRow:
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
        row = conn.execute("SELECT * FROM tracks WHERE filepath = ?", (filepath,)).fetchone()
    return _row_to_track(row) if row else None


def mark_analyzing(db_path: Path, filepath: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE tracks SET status = 'analyzing', error = NULL WHERE filepath = ?", (filepath,))


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
        rows = conn.execute("SELECT * FROM tracks WHERE status = 'analyzed'").fetchall()
    return [_row_to_track(r) for r in rows]


def get_pending_analysis(db_path: Path) -> list[TrackRow]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM tracks WHERE status = 'downloaded'").fetchall()
    return [_row_to_track(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_track_db.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add server/track_db.py tests/test_track_db.py
git commit -m "feat: add SQLite track database for analysis pipeline"
```

---

### Task 2: Analysis sidecar writer

**Files:**
- Create: `server/analysis_store.py`
- Create: `tests/test_analysis_store.py`

**Step 1: Write the failing tests**

```python
# tests/test_analysis_store.py
"""Tests for server/analysis_store.py — analysis sidecar JSON writer/reader."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
    def test_simple_name(self) -> None:
        p = sidecar_path(Path("/config/analysis"), Path("/music/Artist - Title.m4a"))
        assert p == Path("/config/analysis/Artist - Title.meta.json")

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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# server/analysis_store.py
"""Read/write analysis results as sidecar .meta.json files."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from server.models import AnalysisResult

logger = logging.getLogger(__name__)


def sidecar_path(analysis_dir: Path, audio_path: Path) -> Path:
    """Determine the sidecar .meta.json path for an audio file.

    Uses the audio file's stem. If the parent directory differs from a
    simple /audio mount (i.e. could collide), appends a short hash of
    the full path.
    """
    stem = audio_path.stem
    # Add short hash of full path to avoid collisions from different directories
    path_hash = hashlib.sha256(str(audio_path).encode()).hexdigest()[:4]
    candidate = analysis_dir / f"{stem}.meta.json"
    # If no collision risk (first file with this stem), use clean name
    if not candidate.exists():
        return candidate
    # Otherwise append hash
    return analysis_dir / f"{stem}_{path_hash}.meta.json"


def save_analysis(analysis_dir: Path, audio_path: Path, result: AnalysisResult) -> Path:
    """Write analysis result to a sidecar .meta.json file. Returns the output path."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    out_path = sidecar_path(analysis_dir, audio_path)
    data = result.model_dump()
    out_path.write_text(json.dumps(data, indent=2))
    logger.info("Saved analysis to %s", out_path)
    return out_path


def load_analysis(path: Path) -> AnalysisResult | None:
    """Load analysis result from a .meta.json file. Returns None if file doesn't exist."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return AnalysisResult.model_validate(data)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_store.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add server/analysis_store.py tests/test_analysis_store.py
git commit -m "feat: add analysis sidecar .meta.json writer/reader"
```

---

### Task 3: Refactor analyzer.py to use track_db + sidecar

**Files:**
- Modify: `server/analyzer.py`
- Modify: `tests/test_analyzer.py`

**Step 1: Write the failing test**

Add a test to `tests/test_analyzer.py` that verifies analyze_audio writes a sidecar and updates SQLite instead of writing to VDJ:

```python
# Add to tests/test_analyzer.py
async def test_analyze_writes_sidecar_and_updates_db(tmp_path: Path) -> None:
    """After analysis, result should be in .meta.json and SQLite, not VDJ."""
    db_path = tmp_path / "tracks.db"
    analysis_dir = tmp_path / "analysis"
    init_db(db_path)
    filepath = Path("/music/test.m4a")
    upsert_track(db_path, str(filepath))

    # Mock the HTTP call to analyzer service
    result = await analyze_audio(
        filepath,
        db_path=db_path,
        analysis_dir=analysis_dir,
        analyzer_url="http://localhost:9235",
        output_dir=Path("/music"),
    )

    track = get_track(db_path, str(filepath))
    assert track.status == "analyzed"
    assert track.analysis_path is not None
    assert Path(track.analysis_path).exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyzer.py::test_analyze_writes_sidecar_and_updates_db -v`
Expected: FAIL (signature mismatch)

**Step 3: Refactor analyzer.py**

- Remove `vdj_db_path` and `max_cues` parameters from `analyze_audio`
- Add `db_path` and `analysis_dir` parameters
- After successful analysis: call `save_analysis()` and `mark_analyzed()`
- On failure: call `mark_failed()`
- Remove the VDJ write block entirely

Key changes to `analyze_audio` signature:

```python
async def analyze_audio(
    filepath: Path,
    db_path: Path | None = None,
    analysis_dir: Path | None = None,
    analyzer_url: str = "http://localhost:9235",
    output_dir: Path | None = None,
) -> AnalysisResult | None:
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add server/analyzer.py tests/test_analyzer.py
git commit -m "refactor: analyzer writes sidecar + SQLite instead of VDJ"
```

---

### Task 4: VDJ sync module

**Files:**
- Create: `server/vdj_sync.py`
- Create: `tests/test_vdj_sync.py`
- Modify: `server/vdj.py` (add atomic write)

**Step 1: Write the failing tests**

```python
# tests/test_vdj_sync.py
"""Tests for server/vdj_sync.py — VDJ database sync from analysis sidecars."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from unittest.mock import patch

from server.models import AnalysisResult, SegmentInfo
from server.track_db import get_track, init_db, mark_analyzed, upsert_track
from server.vdj_sync import SyncResult, is_vdj_running, sync_vdj

if TYPE_CHECKING:
    from pathlib import Path


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
        bpm=bpm, key="Am", key_camelot="8A",
        beats=[0.234], downbeats=[0.234],
        segments=[SegmentInfo(label="Drop 1 (16 bars)", original_label="chorus", start=60.5, end=90.5, bars=16)],
    ).model_dump()
    from pathlib import Path as P
    P(path).parent.mkdir(parents=True, exist_ok=True)
    P(path).write_text(json.dumps(data))


class TestIsVdjRunning:
    @patch("server.vdj_sync.subprocess.run")
    def test_not_running(self, mock_run) -> None:
        mock_run.return_value.returncode = 1
        assert is_vdj_running() is False

    @patch("server.vdj_sync.subprocess.run")
    def test_running(self, mock_run) -> None:
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vdj_sync.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# server/vdj_sync.py
"""VDJ database sync — batch-write analysis results to database.xml."""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from server.analysis_store import load_analysis
from server.track_db import get_unsynced, mark_synced
from server.vdj import write_to_vdj_database

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    synced: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    refused: bool = False


def is_vdj_running() -> bool:
    if sys.platform == "darwin":
        result = subprocess.run(["pgrep", "-x", "VirtualDJ"], capture_output=True, check=False)
    else:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq VirtualDJ.exe"],
            capture_output=True, check=False,
        )
    return result.returncode == 0


def sync_vdj(db_path: Path, vdj_database_path: Path, max_cues: int = 8) -> SyncResult:
    result = SyncResult()

    if is_vdj_running():
        logger.warning("VirtualDJ is running — refusing to write to database.xml")
        result.refused = True
        return result

    unsynced = get_unsynced(db_path)
    if not unsynced:
        logger.info("No tracks to sync")
        return result

    for track in unsynced:
        if track.analysis_path is None:
            result.skipped += 1
            continue

        from pathlib import Path as P
        analysis = load_analysis(P(track.analysis_path))
        if analysis is None:
            result.errors.append(f"Missing sidecar: {track.analysis_path}")
            continue

        try:
            written = write_to_vdj_database(vdj_database_path, track.filepath, analysis, max_cues=max_cues)
            if written:
                mark_synced(db_path, track.filepath)
                result.synced += 1
            else:
                result.skipped += 1
        except Exception as e:
            result.errors.append(f"{track.filepath}: {e}")
            logger.error("Failed to sync %s", track.filepath, exc_info=True)

    logger.info("Sync complete: %d synced, %d skipped, %d errors", result.synced, result.skipped, len(result.errors))
    return result
```

**Step 4: Update `server/vdj.py` — return bool indicating whether cues were written**

Change `write_to_vdj_database` return type from `None` to `bool`:
- Return `True` if cues were written
- Return `False` if song not found in VDJ (skipped)

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_vdj_sync.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add server/vdj_sync.py tests/test_vdj_sync.py server/vdj.py tests/test_vdj.py
git commit -m "feat: add VDJ sync module with safety checks"
```

---

### Task 5: New API endpoints (sync-vdj, tracks, reanalyze)

**Files:**
- Modify: `server/app.py`
- Modify: `server/models.py`
- Modify: `tests/test_app.py`

**Step 1: Add Pydantic models**

Add to `server/models.py`:

```python
class SyncVdjResponse(BaseModel):
    status: str
    synced: int
    skipped: int
    errors: list[str]
    refused: bool = False

class TrackStatus(BaseModel):
    filepath: str
    status: str
    analysis_path: str | None = None
    error: str | None = None
    analyzed_at: str | None = None
    synced_at: str | None = None

class TracksResponse(BaseModel):
    tracks: list[TrackStatus]

class ReanalyzeRequest(BaseModel):
    filepath: str

class ReanalyzeResponse(BaseModel):
    status: str
```

**Step 2: Write failing tests for the new endpoints**

Add to `tests/test_app.py`:

```python
async def test_sync_vdj_endpoint(client) -> None:
    response = await client.post("/api/sync-vdj")
    assert response.status_code == 200
    data = response.json()
    assert "synced" in data
    assert "refused" in data

async def test_tracks_endpoint(client) -> None:
    response = await client.get("/api/tracks")
    assert response.status_code == 200
    data = response.json()
    assert "tracks" in data

async def test_reanalyze_endpoint(client) -> None:
    response = await client.post("/api/reanalyze", json={"filepath": "/nonexistent.m4a"})
    assert response.status_code == 404
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py -v -k "sync_vdj or tracks_endpoint or reanalyze"`
Expected: FAIL (404 — endpoints don't exist yet)

**Step 4: Implement the endpoints in `server/app.py`**

- `POST /api/sync-vdj` — calls `sync_vdj()` from `server/vdj_sync.py`
- `GET /api/tracks` — reads all tracks from SQLite, returns list
- `POST /api/reanalyze` — resets track to `downloaded`, fires analysis

Initialize the DB on app startup with a `lifespan` or at module level.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add server/app.py server/models.py tests/test_app.py
git commit -m "feat: add sync-vdj, tracks, and reanalyze API endpoints"
```

---

### Task 6: Refactor download endpoint for fire-and-forget analysis

**Files:**
- Modify: `server/app.py`
- Modify: `tests/test_app.py`

**Step 1: Write the failing test**

```python
async def test_download_inserts_track_and_fires_analysis(client, tmp_path) -> None:
    """Download should return immediately and queue analysis in background."""
    # ... mock download + metadata extraction
    # After response, verify:
    # 1. SQLite row exists with status "downloaded" or "analyzing"
    # 2. Response does NOT contain analysis results
    # 3. Response returns quickly (no 10-min analysis wait)
```

**Step 2: Modify download endpoint**

In the download endpoint, after `tag_file()`:
1. Call `upsert_track(db_path, str(final_path))`
2. Fire-and-forget: `asyncio.create_task(analyze_audio(final_path, db_path=..., analysis_dir=...))`
3. Return response immediately (don't await analysis)

Remove the comment about "Analysis is triggered by the extension via POST /api/analyze" — analysis is now server-initiated.

**Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add server/app.py tests/test_app.py
git commit -m "refactor: download fires analysis in background, returns immediately"
```

---

### Task 7: Extension — sync button + track status display

**Files:**
- Modify: `extension/src/api.ts`
- Modify: `extension/src/types.ts`
- Modify: `extension/src/popup.ts`
- Modify: `extension/popup.html`
- Modify: `extension/popup.css`
- Modify: `extension/src/background.ts`

**Step 1: Add TypeScript types**

Add to `extension/src/types.ts`:

```typescript
export interface TrackStatus {
  filepath: string;
  status: string;
  analysis_path: string | null;
  error: string | null;
  analyzed_at: string | null;
  synced_at: string | null;
}

export interface TracksResponse {
  tracks: TrackStatus[];
}

export interface SyncVdjResponse {
  status: string;
  synced: number;
  skipped: number;
  errors: string[];
  refused: boolean;
}
```

**Step 2: Add API functions**

Add to `extension/src/api.ts`:

```typescript
export async function fetchTracks(): Promise<TracksResponse> { ... }
export async function requestSyncVdj(): Promise<SyncVdjResponse> { ... }
export async function requestReanalyze(filepath: string): Promise<void> { ... }
```

**Step 3: Update popup.html**

Add a "Sync to VDJ" button in a footer section below the queue list.

**Step 4: Update popup.ts**

- On popup open, call `fetchTracks()` and merge server-side analysis status into the queue display
- Wire up "Sync to VDJ" button to call `requestSyncVdj()`, show result (synced count, or "VDJ is running" warning)
- Add "Re-analyze" button per track that calls `requestReanalyze(filepath)`

**Step 5: Update background.ts**

- Remove the `requestAnalyze` call after download — server now handles analysis in background
- Simplify: download completes → status is "complete" → done. No more "analyzing"/"analyzed" states in the extension queue.

**Step 6: Build and verify**

Run: `cd extension && npm run build && npm run lint`
Expected: Clean build

**Step 7: Commit**

```bash
git add extension/
git commit -m "feat: add sync-to-VDJ button and track status display in extension"
```

---

### Task 8: Remove old direct-VDJ-write codepath

**Files:**
- Modify: `server/analyzer.py` (remove vdj_db_path references if any remain)
- Modify: `server/app.py` (remove old `/api/analyze` endpoint)
- Modify: `server/models.py` (remove `vdj_written` from AnalysisResult)
- Modify: `extension/src/types.ts` (remove `vdj_written` from AnalysisResult)
- Modify: `extension/src/api.ts` (remove `requestAnalyze`)
- Modify: `tests/test_app.py` (remove old analyze endpoint tests)
- Cleanup: `extension/src/background.ts` (remove analyze import)

**Step 1: Remove `vdj_written` field from AnalysisResult**

In `server/models.py`, remove `vdj_written: bool = False` from `AnalysisResult`.
In `extension/src/types.ts`, remove `vdj_written: boolean` from `AnalysisResult`.

**Step 2: Remove old `/api/analyze` endpoint**

Remove the `analyze` function from `server/app.py` and its import of `AnalyzeRequest`/`AnalyzeResponse` if no longer used.

Keep `AnalyzeRequest` and `AnalyzeResponse` in models.py only if the reanalyze endpoint uses them — otherwise remove.

**Step 3: Remove `requestAnalyze` from extension**

Remove the function from `api.ts` and its import from `background.ts`.

**Step 4: Run full test suite**

Run: `uv run pytest -v && cd extension && npm run build && npm run lint`
Expected: All PASS, clean build

**Step 5: Commit**

```bash
git add server/ tests/ extension/
git commit -m "refactor: remove old direct-VDJ-write codepath"
```

---

## Outcomes & Retrospective

_Filled by /harness:complete when work is done._

**What worked:**
-

**What didn't:**
-

**Learnings to codify:**
-
