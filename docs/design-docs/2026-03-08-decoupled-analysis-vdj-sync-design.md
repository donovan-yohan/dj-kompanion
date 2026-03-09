# Decoupled Analysis & VDJ Sync Design

## Problem

Writing to VDJ's database.xml during analysis causes corruption and race conditions. VDJ reads database.xml on startup only and does not support external modification while running. Analysis currently blocks the download response. No way to re-analyze existing tracks.

## Solution

Three decoupled stages with SQLite tracking:

| Stage | Trigger | Output |
|-------|---------|--------|
| Download + tag | User clicks Download | Audio file + SQLite row (`downloaded`) |
| Analysis | Background queue (fire-and-forget) | `.meta.json` sidecar + SQLite (`analyzed`) |
| VDJ sync | Manual (CLI or extension button) | Cue POIs in database.xml + SQLite (`synced`) |

## Architecture

```
Download ──→ Tag file ──→ Return to user immediately
                  └──→ Queue analysis job (background)
                              ↓
                    Analyzer (GPU/CPU)
                              ↓
                    ~/.config/dj-kompanion/analysis/{stem}.meta.json
                              ↓
                    SQLite: status = "analyzed"
                              ↓
              (user triggers sync, VDJ closed)
                              ↓
                    Read all "analyzed" rows
                    Write cue POIs to database.xml
                    SQLite: status = "synced"
```

## Storage

### SQLite (`~/.config/dj-kompanion/tracks.db`)

```sql
CREATE TABLE tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE NOT NULL,
    analysis_path TEXT,
    status TEXT NOT NULL DEFAULT 'downloaded',
    error TEXT,
    analyzed_at TEXT,
    synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Status values: `downloaded` → `analyzing` → `analyzed` → `synced` | `failed`

### Analysis sidecar (`~/.config/dj-kompanion/analysis/{stem}.meta.json`)

Same shape as `AnalysisResult`:

```json
{
  "bpm": 128.0,
  "key": "Am",
  "key_camelot": "8A",
  "beats": [0.234, 0.703],
  "downbeats": [0.234, 1.172],
  "segments": [
    {"label": "Drop 1 (16 bars)", "original_label": "chorus", "start": 60.5, "end": 90.5, "bars": 16}
  ]
}
```

Filename collisions (same stem from different sources) are resolved with a short hash suffix: `Artist - Title_a3f2.meta.json`.

## Server Changes

### New: `server/track_db.py`

Thin SQLite wrapper:

- `init_db()` — create table if not exists
- `upsert_track(filepath)` — insert or update, set status to `downloaded`
- `mark_analyzing(filepath)` — set status to `analyzing`
- `mark_analyzed(filepath, analysis_path)` — set status to `analyzed`, timestamp
- `mark_synced(filepath)` — set status to `synced`, timestamp
- `mark_failed(filepath, error)` — set status to `failed`, store error
- `get_unsynced()` — all rows where status = `analyzed`
- `get_pending_analysis()` — all rows where status = `downloaded`

### New: `server/vdj_sync.py`

Shared sync function callable from both CLI and API:

```python
def sync_vdj(db_path, vdj_database_path, max_cues) -> SyncResult:
    # 1. Check if VDJ is running — refuse if so
    # 2. Read all unsynced tracks from SQLite
    # 3. For each: load meta.json, write cues to database.xml
    # 4. Mark as synced in SQLite
    # 5. Return summary (synced count, skipped count, errors)
```

VDJ process detection: `pgrep -x "VirtualDJ"` on macOS, `tasklist /FI "IMAGENAME eq VirtualDJ.exe"` on Windows.

### Modified: `server/analyzer.py`

- After analysis completes: write `.meta.json` to `~/.config/dj-kompanion/analysis/`, update SQLite to `analyzed`
- On failure: mark as `failed` in SQLite (retryable via re-analyze)
- No longer calls `write_to_vdj_database` directly

### Modified: `server/app.py`

- `POST /api/download` — after tagging, insert SQLite row as `downloaded`, fire-and-forget analysis (don't await in response)
- `POST /api/sync-vdj` — calls shared `sync_vdj()`, returns summary
- `GET /api/tracks` — returns track list with statuses for extension display
- `POST /api/reanalyze` — accepts filepath, resets to `downloaded`, re-queues analysis

### Preserved: `server/vdj.py`

Cue prioritization and POI writing logic stays. Only called from `vdj_sync.py` during the sync step, never from the analysis pipeline.

## Extension Changes

- Track list shows analysis status from `GET /api/tracks` (polled on popup open)
- "Sync to VDJ" button in popup footer — calls `POST /api/sync-vdj`
- "Re-analyze" button per track for failed or already-synced tracks
- Status indicators: analyzing (spinner), analyzed (ready), synced (checkmark), failed (error + retry)

## CLI

`sync_vdj()` is a direct function that works without the server running — reads SQLite + meta.json, writes to database.xml. This allows syncing even when the server is off.

The extension's sync button calls `POST /api/sync-vdj` which invokes the same underlying function.

## VDJ Database Write Safety

- Only write to database.xml during explicit sync step
- Check VDJ is not running before writing (refuse with warning if it is)
- Preserve all existing VDJ elements (Tags, Infos, Scan, automix POIs, beatgrid)
- Only add/replace `Type="cue"` POIs
- Skip songs not yet in database.xml (VDJ hasn't scanned them)
- Match VDJ's XML formatting: double quotes, CRLF line endings, 1-space indentation
- Write atomically (write to temp file, then rename) to prevent partial writes

## What Stays the Same

- Analyzer container / GPU setup (Proxmox or local Docker)
- Download + tagging pipeline
- LLM enrichment
- VDJ cue prioritization logic (`CUE_PRIORITY`, `prioritize_cues`)
- Config system (`~/.config/dj-kompanion/config.yaml`)
