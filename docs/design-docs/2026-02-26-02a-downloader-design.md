# Downloader Module — Design

**Date:** 2026-02-26
**Status:** Approved
**Phase:** 2a (Parallel Module)
**Parent Design:** `2026-02-26-yt-dlp-dj-design.md`
**Depends On:** Phase 1 (Project Scaffold) must be complete

## Context

yt-dlp-dj is a Chrome extension + Python local server that wraps yt-dlp for one-click music downloading with DJ-ready metadata. This design doc covers the downloader module — the yt-dlp wrapper that handles metadata extraction and audio downloading.

## Goal

A `server/downloader.py` module that:
- Extracts metadata from a URL without downloading (for preview)
- Downloads best available audio from a URL
- Converts to a requested format if needed
- Returns structured metadata matching the `RawMetadata` Pydantic model
- Handles errors gracefully (unsupported URL, network failure, age-restricted content)

## Module Interface

```python
# server/downloader.py

async def extract_metadata(url: str) -> RawMetadata:
    """Extract metadata from URL without downloading.
    Used for the preview step.
    Raises DownloadError on failure."""

async def download_audio(
    url: str,
    output_dir: Path,
    filename: str,
    preferred_format: str = "best",
) -> Path:
    """Download best available audio, optionally convert format.
    Returns the path to the downloaded file.
    Raises DownloadError on failure."""
```

## yt-dlp as Library

Use yt-dlp as a Python library, not as a subprocess:

```python
import yt_dlp

def extract_metadata(url: str) -> RawMetadata:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        # info is a dict with all available metadata
```

Key yt-dlp fields to map to `RawMetadata`:
- `title` → `title`
- `uploader` or `artist` or `creator` → `uploader` (fallback chain)
- `duration` → `duration`
- `upload_date` → `upload_date` (format: YYYYMMDD)
- `description` → `description`
- `tags` or `categories` → `tags` (merge both)
- `webpage_url` or `original_url` → `source_url`

## Download Options

For downloading audio:

```python
ydl_opts = {
    "format": "bestaudio/best",
    "outtmpl": str(output_dir / filename),
    "postprocessors": [],  # added conditionally below
    "quiet": True,
}

if preferred_format != "best":
    ydl_opts["postprocessors"].append({
        "key": "FFmpegExtractAudio",
        "preferredcodec": preferred_format,  # mp3, flac, m4a
        "preferredquality": "0",  # best quality
    })
```

When `preferred_format` is `"best"`, yt-dlp downloads the best available audio format as-is (often opus/webm, m4a, or mp3). When a specific format is requested, ffmpeg converts it.

## Error Handling

```python
class DownloadError(Exception):
    """Raised when yt-dlp extraction or download fails."""
    def __init__(self, message: str, url: str):
        self.message = message
        self.url = url
```

Common failure modes:
- **Unsupported URL** — yt-dlp raises `DownloadError` with "Unsupported URL"
- **Network failure** — yt-dlp raises various network exceptions
- **Age-restricted / geo-blocked** — yt-dlp raises with descriptive message
- **No audio stream available** — handle gracefully, suggest video download instead

All yt-dlp exceptions are caught and re-raised as `DownloadError` with a user-friendly message.

## Source Compatibility

Works with any source yt-dlp supports. Primary targets:
- YouTube (youtube.com, youtu.be, music.youtube.com)
- SoundCloud
- Bandcamp
- Mixcloud
- Any of the 1000+ sites yt-dlp supports

No source-specific code — yt-dlp handles extraction uniformly.

## Testing Strategy

- Unit tests with mocked yt-dlp (don't hit real URLs in CI)
- Test metadata mapping from various yt-dlp info dict shapes (YouTube vs SoundCloud vs Bandcamp return different fields)
- Test error handling paths
- One integration test that actually downloads a short Creative Commons audio clip (marked as slow/optional)

## Success Criteria

- [ ] `extract_metadata(url)` returns structured `RawMetadata` for YouTube, SoundCloud, Bandcamp URLs
- [ ] `download_audio(url, ...)` downloads audio and returns file path
- [ ] Format conversion works (mp3, flac, m4a)
- [ ] Errors are caught and raised as `DownloadError` with clear messages
- [ ] `uv run mypy server/downloader.py` passes strict
- [ ] `uv run pytest tests/test_downloader.py` passes
