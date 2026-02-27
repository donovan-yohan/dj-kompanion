# FastAPI Server & CLI — Design

**Date:** 2026-02-26
**Status:** Approved
**Phase:** 3 (Integration)
**Parent Design:** `2026-02-26-yt-dlp-dj-design.md`
**Depends On:** Phase 1 (Scaffold), Phase 2a (Downloader), 2b (Tagger), 2c (Enrichment)

## Context

yt-dlp-dj is a Chrome extension + Python local server that wraps yt-dlp for one-click music downloading with DJ-ready metadata. This design doc covers the FastAPI server that ties the downloader, tagger, and enrichment modules together behind HTTP endpoints, plus the CLI commands that control it.

## Goal

A working FastAPI server where:
- `yt-dlp-dj serve` starts the server on a configured port
- `POST /api/preview` extracts and enriches metadata from a URL
- `POST /api/download` downloads, tags, and saves audio to the DJ folder
- `yt-dlp-dj download <URL>` does the full pipeline from the command line
- CORS is configured so the Chrome extension can connect

## API Endpoints

### `GET /api/health`

Health check. Returns server status and yt-dlp version.

```json
{
  "status": "ok",
  "yt_dlp_version": "2024.12.06",
  "claude_available": true
}
```

### `POST /api/preview`

Extract metadata from a URL, optionally enrich with LLM.

**Request:**
```json
{ "url": "https://www.youtube.com/watch?v=abc123" }
```

**Response:** `PreviewResponse` (see models.py)
```json
{
  "raw": { "title": "...", "uploader": "...", ... },
  "enriched": { "artist": "...", "title": "...", "genre": "...", ... },
  "enrichment_source": "claude"
}
```

**Flow:**
1. Call `downloader.extract_metadata(url)`
2. Call `enrichment.enrich_metadata(raw_metadata)`
3. Return both raw and enriched

### `POST /api/download`

Download audio, tag it, save to DJ folder.

**Request:** `DownloadRequest`
```json
{
  "url": "https://www.youtube.com/watch?v=abc123",
  "metadata": { "artist": "DJ Snake", "title": "Turn Down for What", ... },
  "format": "best"
}
```

**Response:** `DownloadResponse`
```json
{
  "status": "complete",
  "filepath": "/Users/you/Music/DJ Library/DJ Snake - Turn Down for What.m4a"
}
```

**Flow:**
1. Generate clean filename from metadata
2. Call `downloader.download_audio(url, output_dir, filename, format)`
3. Call `tagger.tag_file(filepath, metadata)`
4. Return final filepath

### `GET /api/download/{id}/status`

SSE (Server-Sent Events) stream for download progress. The download endpoint returns an `id` immediately, and the client can subscribe to progress updates.

This is a stretch goal — v1 can just block until download completes.

### `GET /api/config` / `PUT /api/config`

Read and update the config file via API. Low priority — mainly useful if the extension options page wants to modify server settings.

## CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",  # Chrome extension
    ],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)
```

Note: Chrome extensions use `chrome-extension://EXTENSION_ID` as their origin. During development with an unpacked extension, the ID is unstable — use a wildcard. For production, pin the extension ID.

## Error Responses

All errors return structured JSON:

```json
{
  "error": "download_failed",
  "message": "Unsupported URL: https://example.com/not-a-video",
  "url": "https://example.com/not-a-video"
}
```

HTTP status codes:
- 400 — Bad request (missing URL, invalid format)
- 404 — URL not found / unsupported
- 500 — Internal error (yt-dlp crash, tagging failure)

## CLI Commands

Wire up the typer CLI stubs from Phase 1:

### `yt-dlp-dj serve`
```python
@app.command()
def serve(port: int = None):
    """Start the yt-dlp-dj server."""
    config = load_config()
    port = port or config.server_port
    uvicorn.run("server.app:app", host="127.0.0.1", port=port)
```

### `yt-dlp-dj download <URL>`
```python
@app.command()
def download(url: str, format: str = None):
    """Download and tag audio from URL (no server needed)."""
    config = load_config()
    raw = extract_metadata(url)
    enriched = enrich_metadata(raw)
    # Print enriched metadata for user review
    filepath = download_audio(url, config.output_dir, ...)
    tag_file(filepath, enriched)
    print(f"Saved: {filepath}")
```

The CLI `download` command runs the full pipeline without needing the server — useful for scripting or batch downloads.

## Server Startup

`server/app.py`:

```python
from fastapi import FastAPI
from server.config import load_config

app = FastAPI(title="yt-dlp-dj", version="0.1.0")
config = load_config()

# Mount endpoints...
```

The config is loaded once at startup. If the config file changes, restart the server.

## Testing Strategy

- Test each endpoint with `httpx.AsyncClient` (FastAPI's test client)
- Mock the downloader, tagger, and enrichment modules — this layer is pure integration/routing
- Test error responses for bad URLs, missing fields
- Test CORS headers
- Test CLI commands with `typer.testing.CliRunner`

## Success Criteria

- [ ] `yt-dlp-dj serve` starts server, responds to `/api/health`
- [ ] `POST /api/preview` returns enriched metadata for a valid URL
- [ ] `POST /api/download` downloads, tags, and saves a file
- [ ] `yt-dlp-dj download <URL>` works end-to-end from CLI
- [ ] CORS allows Chrome extension origin
- [ ] Error responses are structured JSON with appropriate status codes
- [ ] `uv run mypy server/app.py` passes strict
- [ ] `uv run pytest tests/test_app.py` passes
