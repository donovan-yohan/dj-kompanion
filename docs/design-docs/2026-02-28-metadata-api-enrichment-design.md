# Metadata API Enrichment — Design

**Date:** 2026-02-28
**Status:** Approved
**Branch:** feat/metadata-enrichment
**Depends On:** Existing enrichment module (`server/enrichment.py`), models (`server/models.py`)

## Context

dj-kompanion currently uses an LLM (Claude via CLI) to clean up raw YouTube metadata — splitting artist/title, stripping "[Official Video]" suffixes, and inferring genre, year, label, and energy. The LLM does well at title cleanup but is unreliable for genre and has no source of truth for album, label, or year.

## Goal

Add external music metadata API lookups (MusicBrainz + Last.fm) to the enrichment pipeline. The APIs provide structured candidate results; the LLM then picks the best match using the original YouTube context. This shifts the LLM from "guess genre" to "pick the right match" — what it's actually good at.

## Architecture: Search-then-Select

### Pipeline (download-time, parallel execution)

```
Download request arrives
  |
  v
basic_enrich(raw) -> extract artist + title for search queries
  |
  v
Run in parallel:
  ├── yt-dlp download (existing, 3-10s)
  └── search_metadata(artist, title) (NEW, 1-2s)
       |
       v
       Claude enrichment with API candidates (MODIFIED, ~3s)
  |
  v
merge_metadata(user, claude_with_candidates, user_edited_fields)
  |
  v
tag_file + return response
```

Sequencing: API search and yt-dlp run truly in parallel. Claude starts after API search completes (needs candidates). Since download takes 3-10s and API search takes 1-2s, Claude still starts well before download finishes.

### Fallback Chain

1. **API candidates + Claude selects** → `enrichment_source: "api+claude"` — best accuracy
2. **No API results + Claude infers** → `enrichment_source: "claude"` — current behavior, no regression
3. **Claude fails** → `enrichment_source: "basic"` — basic_enrich fallback (existing)
4. **User-edited fields always override**, regardless of enrichment source

No auto-pick from API candidates without LLM validation — too risky for wrong matches.

## New Module: `server/metadata_lookup.py`

```python
@dataclass
class MetadataCandidate:
    source: str              # "musicbrainz" or "lastfm"
    artist: str
    title: str
    album: str | None
    label: str | None
    year: int | None
    genre_tags: list[str]    # e.g. ["house", "deep house", "electronic"]
    match_score: float       # 0-100, from API search ranking
    musicbrainz_id: str | None
    cover_art_url: str | None

async def search_metadata(artist: str, title: str) -> list[MetadataCandidate]:
    """Search MusicBrainz + Last.fm for metadata candidates.

    Runs both searches in parallel. Returns combined list sorted by match_score.
    Never raises — returns empty list on failure.
    """
```

### MusicBrainz Search

Uses `musicbrainzngs.search_recordings(artist=artist, recording=title, limit=5)`.

Each result includes: artist credits, release (album), release date (year), label (via release includes), tags, and cover art URL from the Cover Art Archive.

Requires setting a User-Agent string: `dj-kompanion/1.0 (contact@example.com)`.

Rate limit: 1 request per second. Fine for single-user tool.

### Last.fm Search

Uses `pylast` to call `track.search` + `track.getTopTags`.

Returns genre tags ordered by popularity (e.g., `["house", "electronic", "dance"]`).

Requires a free API key (register at last.fm/api/account/create).

If no API key configured, Last.fm search is silently skipped.

### Remix Handling

If the title contains remix indicators (`remix`, `edit`, `bootleg`, `VIP`, `flip`), the search:
- Searches for both the original track name and the full title with remix artist
- Example: "Skrillex - Rumble (Fred again.. Remix)" → search "Skrillex Rumble" AND "Skrillex Rumble Fred again remix"

## Modified Claude Prompt

The LLM receives raw YouTube metadata + API candidates and selects the best match:

```
You are a metadata matcher for DJ music files. You have raw metadata from a YouTube
download AND search results from music databases. Your job is to:

1. Determine which search result (if any) matches this actual song
2. Extract the best metadata by combining the match with raw context
3. If no result matches, infer metadata as best you can

Raw metadata from download:
{raw_metadata_json}

Search results from music databases:
{candidates_json}

Rules:
- Pick the search result that matches this SPECIFIC recording (not just same artist)
- For remixes: match the REMIX version, not the original. "Artist - Song (Remixer Remix)"
  should match a release that credits the remixer, not the original release. If only the
  original is in results, say no_match rather than using wrong release metadata.
- Genre: prefer the API genre tags, pick the most specific applicable one
  (e.g. "deep house" over "electronic")
- If no search result matches well, say "no_match" and infer like before
- Energy level 1-10 is always your inference (APIs don't have this)
- cover_art_url: pass through from the selected candidate if available

Return ONLY valid JSON:
{
  "selected_candidate_index": number or null,
  "confidence": "high" | "medium" | "low",
  "artist": "string",
  "title": "string",
  "album": "string or null",
  "genre": "string or null",
  "year": number or null,
  "label": "string or null",
  "energy": number 1-10 or null,
  "bpm": null,
  "key": null,
  "comment": "source URL",
  "cover_art_url": "string or null"
}
```

Key changes from current prompt:
- Adds `selected_candidate_index` and `confidence` for provenance tracking
- Adds `album` field (new — pulled from API, not in current EnrichedMetadata)
- Adds `cover_art_url` pass-through from selected candidate
- Explicit remix handling instructions with examples
- LLM's job shifts from "guess genre" to "pick the right match"
- Energy remains LLM-inferred (no API source)

## Model Changes

### EnrichedMetadata (updated)

New fields:
- `album: str | None = None`
- `cover_art_url: str | None = None`

### enrichment_source (updated Literal)

- `"api+claude"` — API candidates found, Claude selected a match
- `"claude"` — Claude inferred without API data
- `"basic"` — basic_enrich only
- `"none"` — preview-time, no enrichment run yet

The frontend can use this to display provenance (e.g., a badge or icon).

### User Edit Priority (unchanged)

The existing `merge_metadata` function and `user_edited_fields` tracking continue to work exactly as before. User-edited fields always override, regardless of enrichment source.

## Configuration

New config section in `~/.config/dj-kompanion/config.toml`:

```toml
[metadata_lookup]
enabled = true
lastfm_api_key = ""                    # Free key from last.fm/api/account/create
musicbrainz_user_agent = "dj-kompanion/1.0"
search_limit = 5                       # Max results per API
```

New Pydantic config model:

```python
class MetadataLookupConfig(BaseModel):
    enabled: bool = True
    lastfm_api_key: str = ""
    musicbrainz_user_agent: str = "dj-kompanion/1.0"
    search_limit: int = 5
```

## Dependencies

New Python packages (added to `pyproject.toml`):
- `musicbrainzngs` — MusicBrainz API client (MIT, pure Python)
- `pylast` — Last.fm API client (Apache 2.0, pure Python)

No native dependencies. No Docker changes needed.

## Extension Changes

- TypeScript `EnrichedMetadata` interface gets `album` and `cover_art_url` fields
- `enrichment_source` type updated with `"api+claude"` value
- Popup can optionally display enrichment source as a visual indicator
- Album art display is a future enhancement (not in scope for this design)

## Testing Strategy

- Mock `musicbrainzngs` and `pylast` responses in tests
- Test search_metadata with various query shapes (normal, remix, no results)
- Test modified Claude prompt parsing with candidates
- Test fallback chain: API+Claude, Claude-only, basic_enrich
- Test that user_edited_fields priority is preserved
- Integration test: full download flow with mocked APIs

## Success Criteria

- [ ] `search_metadata()` returns candidates from MusicBrainz + Last.fm
- [ ] Modified Claude prompt correctly selects from candidates
- [ ] Fallback chain works: api+claude → claude → basic
- [ ] User-edited fields always preserved
- [ ] `enrichment_source` accurately reflects which path was taken
- [ ] No added wall-clock time (API search runs parallel with download)
- [ ] Graceful degradation when APIs are unavailable
- [ ] `uv run mypy server/` passes strict
- [ ] `uv run pytest` passes

## API References

- [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API) — Rate limit: 1 req/sec, User-Agent required
- [MusicBrainz API Search](https://musicbrainz.org/doc/MusicBrainz_API/Search)
- [Last.fm API](https://www.last.fm/api) — Free API key required
- [musicbrainzngs Python library](https://python-musicbrainzngs.readthedocs.io/)
- [pylast Python library](https://github.com/pylast/pylast)
- [Cover Art Archive](https://coverartarchive.org/)
