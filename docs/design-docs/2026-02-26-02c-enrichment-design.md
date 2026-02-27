# LLM Enrichment Module — Design

**Date:** 2026-02-26
**Status:** Approved
**Phase:** 2c (Parallel Module)
**Parent Design:** `2026-02-26-dj-kompanion-design.md`
**Depends On:** Phase 1 (Project Scaffold) must be complete

## Context

dj-kompanion is a Chrome extension + Python local server that wraps yt-dlp for one-click music downloading with DJ-ready metadata. This design doc covers the LLM enrichment module — the component that uses the `claude` CLI to clean up messy metadata from yt-dlp into well-structured DJ-ready tags.

## Goal

A `server/enrichment.py` module that:
- Takes a `RawMetadata` object (from yt-dlp)
- Shells out to `claude -p --model haiku` to parse and enrich the metadata
- Returns an `EnrichedMetadata` object with clean artist/title, inferred genre, etc.
- Falls back gracefully when `claude` CLI is not available or fails

## Module Interface

```python
# server/enrichment.py

async def enrich_metadata(raw: RawMetadata, model: str = "haiku") -> EnrichedMetadata:
    """Use claude CLI to parse and enrich raw metadata.
    Falls back to basic parsing if claude is unavailable.
    Never raises — always returns an EnrichedMetadata."""

def basic_enrich(raw: RawMetadata) -> EnrichedMetadata:
    """Fallback enrichment without LLM.
    Attempts basic artist/title splitting from common YouTube title patterns."""

async def is_claude_available() -> bool:
    """Check if claude CLI is on PATH and authenticated."""
```

## LLM Strategy

Shell out to `claude` CLI in print mode:

```python
import subprocess
import json

result = subprocess.run(
    ["claude", "-p", "--model", model, "--output-format", "json", prompt],
    capture_output=True,
    text=True,
    timeout=30,
)
```

### Prompt Design

The prompt is a structured parsing task — no creativity needed:

```
You are a metadata parser for DJ music files. Given raw metadata from a music download,
extract clean, accurate metadata.

Rules:
- Separate artist from title (YouTube titles often combine them with " - ", " | ", " // ")
- Remove quality indicators: [HD], [4K], (Official Video), (Official Audio), (Lyrics), etc.
- Remove channel self-promotion suffixes
- Infer genre from title, description, tags, and channel context
- Estimate energy level 1-10 (1=ambient/chill, 5=moderate, 10=hard/intense)
- Use release year, not upload year, when inferable from description
- Extract label name if mentioned in description or tags
- If unsure about a field, return null

Raw metadata:
{raw_metadata_json}

Return ONLY valid JSON matching this schema:
{
  "artist": "string",
  "title": "string",
  "genre": "string or null",
  "year": "number or null",
  "label": "string or null",
  "energy": "number 1-10 or null",
  "bpm": null,
  "key": null,
  "comment": "source URL"
}
```

BPM and key are always null — they can't be inferred from text metadata alone.

## Fallback Parsing (No LLM)

When `claude` is not available, `basic_enrich()` handles common patterns:

```python
def basic_enrich(raw: RawMetadata) -> EnrichedMetadata:
    """Split artist/title from common YouTube patterns."""
    title = raw.title

    # Try "Artist - Title" pattern
    if " - " in title:
        artist, title = title.split(" - ", 1)
    else:
        artist = raw.uploader or "Unknown"

    # Strip common suffixes
    for suffix in ["(Official Video)", "(Official Audio)", "[HD]", "(Lyrics)", ...]:
        title = title.replace(suffix, "").strip()

    return EnrichedMetadata(
        artist=artist.strip(),
        title=title.strip(),
        comment=raw.source_url,
    )
```

This won't infer genre/energy/year, but it handles the most common title format.

## Error Handling

This module **never raises exceptions** to callers. The LLM is optional — if it fails for any reason, we fall back:

1. `claude` not on PATH → use `basic_enrich()`
2. `claude` times out (30s) → use `basic_enrich()`
3. `claude` returns invalid JSON → use `basic_enrich()`
4. `claude` returns unexpected schema → merge what we can, fill rest from `basic_enrich()`

The `enrichment_source` field in `PreviewResponse` tells the extension which path was used: `"claude"` or `"none"`.

## Testing Strategy

- Mock `subprocess.run` to test claude CLI integration without actual API calls
- Test prompt construction with various raw metadata shapes
- Test JSON response parsing (valid, invalid, partial)
- Test fallback path (`basic_enrich`) with common YouTube title patterns:
  - `"DJ Snake - Turn Down for What (Official Video) [HD]"`
  - `"Turn Down for What"`  (no artist separator)
  - `"Fred again.. & Skrillex - Baby again.."`  (dots and ampersands in names)
  - `"Bicep | GLUE (Official Video)"`  (pipe separator)
- Test `is_claude_available()` with mocked PATH

## Success Criteria

- [ ] `enrich_metadata()` returns valid `EnrichedMetadata` when claude succeeds
- [ ] `enrich_metadata()` falls back to `basic_enrich()` when claude is unavailable
- [ ] `basic_enrich()` correctly splits common YouTube title formats
- [ ] Prompt produces accurate results for typical music titles (manual verification)
- [ ] 30-second timeout prevents hanging
- [ ] `uv run mypy server/enrichment.py` passes strict
- [ ] `uv run pytest tests/test_enrichment.py` passes
