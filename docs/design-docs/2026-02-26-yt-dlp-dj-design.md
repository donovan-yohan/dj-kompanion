# dj-kompanion Design

**Date:** 2026-02-26
**Status:** Approved

## Problem

Downloading music from YouTube/SoundCloud/Bandcamp for DJ use requires running yt-dlp manually, cleaning up messy metadata by hand, tagging files in a format Virtual DJ understands, and organizing into the right folder. This is tedious and error-prone.

## Solution

A Chrome extension + Python local server that provides one-click preview-and-download with LLM-assisted metadata enrichment, outputting properly tagged audio files ready for Virtual DJ.

## Architecture

```
┌─────────────────────┐         HTTP (localhost)        ┌─────────────────────────┐
│  Chrome Extension   │ ◄──────────────────────────────►│   Python Local Server   │
│  (Manifest V3)      │                                 │   (FastAPI)             │
│                     │   POST /api/preview             │                         │
│  - Popup UI (TS)    │ ──────────────────────────────► │  - yt-dlp (library)     │
│  - Edit metadata    │   ◄── metadata JSON             │  - mutagen (tagging)    │
│  - Confirm download │                                 │  - claude CLI (LLM)     │
│                     │   POST /api/download            │  - pydantic (models)    │
│                     │ ──────────────────────────────► │                         │
│                     │   ◄── status/progress           │  Output: DJ folder      │
└─────────────────────┘                                 └─────────────────────────┘
```

**Components:**
1. **Chrome Extension (Manifest V3, TypeScript)** — Thin UI. Grabs current tab URL, sends to server, displays metadata for editing, confirms download.
2. **Python Server (FastAPI)** — The brain. yt-dlp for extraction/download, mutagen for tagging, claude CLI for LLM enrichment.
3. **Config** — `~/.config/dj-kompanion/config.yaml` for output folder, format preferences, LLM settings.

**Key decisions:**
- FastAPI over Flask — async support, built-in OpenAPI docs
- yt-dlp as Python library, not subprocess — direct metadata access, proper error handling
- LLM enrichment is optional — works without claude CLI

## Data Flow

### Step 1: Preview (no download)
```
URL → yt-dlp.extract_info(download=False) → raw metadata dict
```

### Step 2: LLM Enrichment (optional)
Shell out to `claude -p --model haiku --output-format json` with the raw metadata. The LLM:
- Parses artist/title from messy YouTube titles
- Infers genre from title, description, tags, channel context
- Estimates energy level (1-10)
- Suggests year (release year, not upload year)
- Suggests label if mentioned in description/tags

No API key management needed — uses existing Claude Code authentication.

### Step 3: Present to User
Extension popup shows editable form with enriched metadata:

| Field | Source | Editable |
|-------|--------|----------|
| Artist | LLM-parsed or raw `uploader` | Yes |
| Title | LLM-parsed or raw `title` | Yes |
| Genre | LLM-inferred | Yes |
| Year | LLM-inferred or `upload_date` year | Yes |
| Label | LLM-inferred or empty | Yes |
| Energy | LLM-estimated (1-10) | Yes |
| BPM | Empty (manual entry) | Yes |
| Key | Empty (manual entry) | Yes |
| Comment | Auto-filled with source URL | Yes |

### Step 4: Download & Tag
```
yt-dlp download (best audio) → ffmpeg convert if needed → mutagen embed tags → save to DJ folder
```

Filename: `{Artist} - {Title}.{ext}` with filesystem-unsafe characters stripped.

## Chrome Extension UX

Three states:
1. **Initial** — Shows current tab URL, server health status, "Fetch Metadata" button
2. **Preview** — Editable metadata form, format selector (Best / MP3 / FLAC), "Download" button
3. **Complete** — Success confirmation with filename, output path, "Open Folder" link

If server is not running: clear message with "Start the local server first: `dj-kompanion serve`"

Extension icon badge shows indicator during download. Connection to `http://localhost:PORT` (configurable in extension options page).

## Server API

```
GET  /api/health              → { status, yt_dlp_version }
POST /api/preview             → { url } → { raw, enriched, enrichment_source }
POST /api/download            → { url, metadata, format } → { status, filepath }
GET  /api/download/{id}/status → SSE stream for download progress
GET  /api/config              → current config
PUT  /api/config              → update config
```

**CLI commands:**
```
dj-kompanion serve              # Start server (default port 9234)
dj-kompanion serve -p 8080      # Custom port
dj-kompanion config             # Open/create config file
dj-kompanion download <URL>     # Direct CLI download (no browser)
```

## Tagging Strategy

Write all metadata to file tags via mutagen. Let Virtual DJ pick up what it natively reads.

| Field | MP3 (ID3v2.4) | FLAC (Vorbis) | M4A (MP4) |
|-------|---------------|---------------|-----------|
| Artist | TPE1 | ARTIST | \xa9ART |
| Title | TIT2 | TITLE | \xa9nam |
| Genre | TCON | GENRE | \xa9gen |
| Year | TDRC | DATE | \xa9day |
| Label | TPUB | LABEL | ----:com.apple.iTunes:LABEL |
| Energy | TXXX:ENERGY | ENERGY | ----:com.apple.iTunes:ENERGY |
| BPM | TBPM | BPM | tmpo |
| Key | TKEY | INITIALKEY | ----:com.apple.iTunes:initialkey |
| Comment | COMM | COMMENT | \xa9cmt |

VDJ natively reads: Artist, Title, Genre, Year, BPM, Key, Comment. Custom fields (Energy, Label) are preserved in file tags for portability but may need manual confirmation in VDJ.

## Config

`~/.config/dj-kompanion/config.yaml`:
```yaml
output_dir: ~/Music/DJ Library
preferred_format: best  # best | mp3 | flac | m4a
filename_template: "{artist} - {title}"
server_port: 9234

llm:
  enabled: true
  model: haiku  # passed as --model flag to claude CLI
```

## Project Structure

```
dj-kompanion/
├── CLAUDE.md
├── docs/
├── pyproject.toml               # ruff, mypy, pytest config
│
├── server/
│   ├── __init__.py
│   ├── py.typed                 # PEP 561 marker
│   ├── app.py                   # FastAPI app, endpoints
│   ├── cli.py                   # typer CLI
│   ├── config.py                # Config loading/validation
│   ├── models.py                # Pydantic models
│   ├── downloader.py            # yt-dlp wrapper
│   ├── enrichment.py            # LLM enrichment via claude CLI
│   └── tagger.py                # mutagen tagging logic
│
├── extension/
│   ├── tsconfig.json            # strict: true
│   ├── .eslintrc.json
│   ├── .prettierrc
│   ├── package.json             # esbuild, eslint, prettier, typescript
│   ├── src/
│   │   ├── popup.ts
│   │   ├── background.ts
│   │   ├── options.ts
│   │   └── types.ts             # shared types
│   ├── dist/                    # esbuild output (gitignored)
│   ├── popup.html
│   ├── popup.css
│   ├── options.html
│   ├── manifest.json
│   └── icons/
│
└── tests/
    ├── test_downloader.py
    ├── test_enrichment.py
    └── test_tagger.py
```

## Dependencies

**Python:**
- fastapi, uvicorn — web server
- yt-dlp — download + metadata extraction
- mutagen — audio file tagging
- typer — CLI interface
- pyyaml — config file parsing
- pydantic — data validation (comes with FastAPI)

**Python dev:**
- mypy (strict mode) — static type checking
- ruff — linting + formatting
- pytest — tests

**Extension:**
- typescript (strict mode) — type safety
- esbuild — bundler
- eslint + prettier — linting + formatting

## Shared Type Contract

Server (Pydantic) and extension (TypeScript) both define the same `EnrichedMetadata` shape. Kept in sync manually — the surface area is small (one model).

## Quick Reference

| Action | Command |
|--------|---------|
| Server dev | `uv run uvicorn server.app:app --reload` |
| Type check (Python) | `uv run mypy server/` |
| Lint + format (Python) | `uv run ruff check . && uv run ruff format .` |
| Test | `uv run pytest` |
| Build extension | `cd extension && npm run build` |
| Lint + format (Extension) | `cd extension && npm run lint && npm run format` |
| Type check (Extension) | `cd extension && npx tsc --noEmit` |
