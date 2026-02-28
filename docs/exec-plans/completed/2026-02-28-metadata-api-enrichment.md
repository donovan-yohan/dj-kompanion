# Metadata API Enrichment Implementation Plan

> **Status**: Completed | **Created**: 2026-02-28 | **Completed**: 2026-02-28
> **Design Doc**: `docs/design-docs/2026-02-28-metadata-api-enrichment-design.md`
> **For Claude:** Use /harness:orchestrate to execute this plan.
> **REQUIRED SUB-SKILL:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add MusicBrainz + Last.fm metadata lookups to the enrichment pipeline so the LLM selects from real database results instead of guessing genre/album/label/year.

**Architecture:** New `server/metadata_lookup.py` module searches MusicBrainz and Last.fm in parallel, returning structured `MetadataCandidate` objects. The existing Claude enrichment prompt is modified to receive these candidates and select the best match. The API search runs in parallel with yt-dlp download at download time, so there's zero added wall-clock time. Fallback chain: api+claude → claude → basic.

**Tech Stack:** Python 3.11+, musicbrainzngs (MusicBrainz API), pylast (Last.fm API), FastAPI, Pydantic, pytest

**API Reference Docs (for subagents):**
- `docs/references/musicbrainz-api.md` — Full MusicBrainz API + musicbrainzngs usage with code examples
- `docs/references/lastfm-api.md` — Full Last.fm API + pylast usage with code examples
- Online: https://python-musicbrainzngs.readthedocs.io/en/latest/api/
- Online: https://github.com/pylast/pylast
- Online: https://musicbrainz.org/doc/MusicBrainz_API/Search
- Online: https://www.last.fm/api/show/track.search
- Online: https://www.last.fm/api/show/track.getTopTags
- Online: https://www.last.fm/api/show/track.getInfo
- Online: https://coverartarchive.org/

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-02-28 | Design | MusicBrainz + Last.fm as API sources | Complementary strengths: MB for album/label/year, Last.fm for genre tags. Both free, no OAuth. |
| 2026-02-28 | Design | Search-then-Select pattern | APIs provide candidates, LLM picks best match. LLM does reasoning (its strength), not guessing (its weakness). |
| 2026-02-28 | Design | Download-time parallel execution | API search + yt-dlp run concurrently. Claude starts after API search completes. Zero added wait time. |
| 2026-02-28 | Design | LLM decides match quality | LLM rates confidence (high/medium/low/no_match). No auto-pick from API without LLM validation. |
| 2026-02-28 | Design | Skip auto-pick fallback | If Claude fails, fall back to basic_enrich, not API top result. Too risky for wrong matches without LLM. |
| 2026-02-28 | Design | Track enrichment source | `enrichment_source` field tracks provenance: api+claude, claude, basic, none. Frontend displays this. |
| 2026-02-28 | Retrospective | Plan completed | All 10 tasks implemented, 177 tests pass, mypy clean, extension builds. 4 minor surprises, no plan drift. |

## Progress

- [x] Task 1: Add dependencies and config model _(completed 2026-02-28)_
- [x] Task 2: Update Pydantic models (EnrichedMetadata, enrichment_source) _(completed 2026-02-28)_
- [x] Task 3: Build MusicBrainz search function _(completed 2026-02-28)_
- [x] Task 4: Build Last.fm search function _(completed 2026-02-28)_
- [x] Task 5: Build combined search_metadata orchestrator _(completed 2026-02-28)_
- [x] Task 6: Update Claude prompt for candidate selection _(completed 2026-02-28)_
- [x] Task 7: Wire into download endpoint (parallel execution) _(completed 2026-02-28)_
- [x] Task 8: Update TypeScript types in extension _(completed 2026-02-28)_
- [x] Task 9: Integration test — full download flow with mocked APIs _(completed 2026-02-28)_
- [x] Task 10: Lint, type-check, and final verification _(completed 2026-02-28)_

## Surprises & Discoveries

| Date | What | Impact | Resolution |
|------|------|--------|------------|
| 2026-02-28 | uv.lock is gitignored in worktree | Minor — lock file excluded from commit | No action needed, pyproject.toml is sufficient |
| 2026-02-28 | musicbrainzngs mypy override `follow_imports = "skip"` doesn't suppress `import-untyped` on bare import | Minor — needed `# type: ignore[import-untyped]` on import line | Added inline ignore comment; pyproject.toml override still useful for deeper imports |
| 2026-02-28 | pylast has type stubs — `# type: ignore[import-untyped]` not needed | Positive — pylast import is clean, no mypy workaround needed | Used bare `import pylast`; pyproject.toml override for pylast may be unnecessary |
| 2026-02-28 | Existing app tests needed `search_metadata` mocked | `metadata_lookup.enabled` defaults True, so existing tests would call real network function | Added mock to 3 existing tests; added new test for api+claude flow |

## Plan Drift

_None yet — updated when tasks deviate from plan during execution._

---

### Task 1: Add Dependencies and Config Model

**Files:**
- Modify: `pyproject.toml` (add musicbrainzngs, pylast)
- Modify: `server/config.py` (add MetadataLookupConfig)
- Test: `tests/test_config.py` (if exists, or manual verification)

**Reference:** `docs/references/musicbrainz-api.md` (Setup section), `docs/references/lastfm-api.md` (Setup section)

**Step 1: Add Python dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```toml
dependencies = [
    "fastapi",
    "uvicorn",
    "yt-dlp[default]",
    "mutagen",
    "typer",
    "pyyaml",
    "pydantic",
    "httpx",
    "musicbrainzngs",
    "pylast",
]
```

Also add type stubs to dev dependencies:

```toml
[dependency-groups]
dev = [
    "mypy>=1.19.1",
    "pytest>=9.0.2",
    "ruff>=0.15.4",
    "types-pyyaml>=6.0.12.20250915",
    "httpx>=0.27",
    "pytest-asyncio>=0.24",
]
```

Note: musicbrainzngs and pylast don't have official type stubs. We'll need mypy overrides for them (see Step 3).

**Step 2: Install dependencies**

Run: `uv sync`
Expected: All packages install successfully.

**Step 3: Add mypy overrides for untyped libraries**

In `pyproject.toml`, add overrides for the new untyped libraries:

```toml
[[tool.mypy.overrides]]
module = "musicbrainzngs.*"
follow_imports = "skip"

[[tool.mypy.overrides]]
module = "pylast.*"
follow_imports = "skip"
```

**Step 4: Add MetadataLookupConfig to config.py**

In `server/config.py`, add the new config model and wire it into `AppConfig`:

```python
class MetadataLookupConfig(BaseModel):
    enabled: bool = True
    lastfm_api_key: str = ""
    musicbrainz_user_agent: str = "dj-kompanion/1.0"
    search_limit: int = 5
```

Add to `AppConfig`:

```python
class AppConfig(BaseModel):
    output_dir: Path = Path("~/Music/DJ Library").expanduser()
    preferred_format: str = "best"
    filename_template: str = "{artist} - {title}"
    server_port: int = 9234
    llm: LLMConfig = LLMConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    metadata_lookup: MetadataLookupConfig = MetadataLookupConfig()
```

Update `_serializable_defaults()` to include the new section:

```python
def _serializable_defaults() -> dict[str, object]:
    config = AppConfig()
    data = config.model_dump()
    data["output_dir"] = str(config.output_dir)
    data["analysis"] = {
        "enabled": config.analysis.enabled,
        "vdj_database": str(config.analysis.vdj_database),
        "max_cues": config.analysis.max_cues,
        "analyzer_url": config.analysis.analyzer_url,
    }
    # metadata_lookup is all primitives, no Path conversion needed
    return data
```

**Step 5: Verify**

Run: `uv run mypy server/config.py`
Expected: PASS with no errors.

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock server/config.py
git commit -m "feat(config): add musicbrainzngs + pylast deps and MetadataLookupConfig"
```

---

### Task 2: Update Pydantic Models

**Files:**
- Modify: `server/models.py` (add album, cover_art_url to EnrichedMetadata; update enrichment_source Literal)

**Step 1: Add new fields to EnrichedMetadata**

In `server/models.py`, update `EnrichedMetadata`:

```python
class EnrichedMetadata(BaseModel):
    artist: str
    title: str
    album: str | None = None
    genre: str | None = None
    year: int | None = None
    label: str | None = None
    energy: int | None = None
    bpm: int | None = None
    key: str | None = None
    cover_art_url: str | None = None
    comment: str = ""
```

**Step 2: Update enrichment_source Literals**

In `PreviewResponse`, keep as-is (preview still only returns `"claude" | "none"`).

In `DownloadResponse`, update:

```python
class DownloadResponse(BaseModel):
    status: str
    filepath: str
    enrichment_source: Literal["api+claude", "claude", "basic", "none"] = "none"
    metadata: EnrichedMetadata | None = None
```

**Step 3: Run existing tests to confirm backward compatibility**

Run: `uv run pytest tests/ -v`
Expected: All existing tests PASS. The new fields have defaults so nothing breaks.

**Step 4: Run type check**

Run: `uv run mypy server/models.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/models.py
git commit -m "feat(models): add album, cover_art_url fields and api+claude enrichment source"
```

---

### Task 3: Build MusicBrainz Search Function

**Files:**
- Create: `server/metadata_lookup.py`
- Create: `tests/test_metadata_lookup.py`

**Reference:** `docs/references/musicbrainz-api.md` — Search Recordings section, Response Structure section, Getting Label Info section, Cover Art Archive section

**Step 1: Write the MetadataCandidate dataclass and MusicBrainz test**

Create `tests/test_metadata_lookup.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

from server.metadata_lookup import MetadataCandidate, search_musicbrainz


def _mb_recording(
    title: str = "Rumble",
    artist: str = "Skrillex",
    score: str = "100",
    release_title: str = "Quest For Fire",
    release_date: str = "2023-02-17",
    release_id: str = "abc-123",
    label_name: str | None = "OWSLA",
    tags: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build a fake MusicBrainz recording result."""
    rec: dict[str, object] = {
        "id": "rec-001",
        "title": title,
        "ext:score": score,
        "artist-credit": [{"artist": {"name": artist}}],
        "release-list": [
            {
                "id": release_id,
                "title": release_title,
                "date": release_date,
                "status": "Official",
            }
        ],
    }
    if tags:
        rec["tag-list"] = tags
    return rec


def test_search_musicbrainz_returns_candidates() -> None:
    mb_result = {
        "recording-list": [
            _mb_recording(
                title="Rumble",
                artist="Skrillex",
                score="95",
                release_title="Quest For Fire",
                release_date="2023-02-17",
                release_id="rel-001",
                tags=[{"name": "dubstep", "count": "5"}, {"name": "electronic", "count": "3"}],
            ),
        ],
    }

    with patch("server.metadata_lookup.musicbrainzngs") as mock_mb:
        mock_mb.search_recordings.return_value = mb_result
        mock_mb.get_release_by_id.return_value = {
            "release": {"label-info-list": [{"label": {"name": "OWSLA"}}]}
        }
        results = search_musicbrainz("Skrillex", "Rumble", limit=5)

    assert len(results) == 1
    c = results[0]
    assert c.source == "musicbrainz"
    assert c.artist == "Skrillex"
    assert c.title == "Rumble"
    assert c.album == "Quest For Fire"
    assert c.year == 2023
    assert c.label == "OWSLA"
    assert "dubstep" in c.genre_tags
    assert c.match_score == 95.0
    assert c.cover_art_url is not None


def test_search_musicbrainz_handles_api_error() -> None:
    with patch("server.metadata_lookup.musicbrainzngs") as mock_mb:
        mock_mb.WebServiceError = Exception
        mock_mb.search_recordings.side_effect = Exception("503 rate limited")
        results = search_musicbrainz("Skrillex", "Rumble", limit=5)

    assert results == []


def test_search_musicbrainz_handles_missing_fields() -> None:
    mb_result = {
        "recording-list": [
            {
                "id": "rec-002",
                "title": "Unknown Track",
                "ext:score": "60",
                "artist-credit": [{"artist": {"name": "Unknown"}}],
                # No release-list, no tag-list
            },
        ],
    }

    with patch("server.metadata_lookup.musicbrainzngs") as mock_mb:
        mock_mb.search_recordings.return_value = mb_result
        results = search_musicbrainz("Unknown", "Unknown Track", limit=5)

    assert len(results) == 1
    c = results[0]
    assert c.album is None
    assert c.year is None
    assert c.label is None
    assert c.genre_tags == []
    assert c.cover_art_url is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_lookup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.metadata_lookup'`

**Step 3: Create metadata_lookup.py with MetadataCandidate and search_musicbrainz**

Create `server/metadata_lookup.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import musicbrainzngs  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class MetadataCandidate:
    source: str
    artist: str
    title: str
    album: str | None = None
    label: str | None = None
    year: int | None = None
    genre_tags: list[str] = field(default_factory=list)
    match_score: float = 0.0
    musicbrainz_id: str | None = None
    cover_art_url: str | None = None


_MB_INITIALIZED = False


def _ensure_mb_init(user_agent: str) -> None:
    global _MB_INITIALIZED
    if not _MB_INITIALIZED:
        parts = user_agent.split("/", 1)
        app_name = parts[0] if parts else "dj-kompanion"
        version = parts[1] if len(parts) > 1 else "1.0"
        musicbrainzngs.set_useragent(app_name, version)
        _MB_INITIALIZED = True


def _extract_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, IndexError):
        return None


def _get_label_for_release(release_id: str) -> str | None:
    try:
        result = musicbrainzngs.get_release_by_id(release_id, includes=["labels"])
        release = result.get("release", {})
        label_info_list = release.get("label-info-list", [])
        if label_info_list:
            label = label_info_list[0].get("label", {})
            return label.get("name") if label else None
    except Exception:
        logger.debug("Failed to fetch label for release %s", release_id)
    return None


def search_musicbrainz(
    artist: str,
    title: str,
    limit: int = 5,
    user_agent: str = "dj-kompanion/1.0",
) -> list[MetadataCandidate]:
    """Search MusicBrainz for recording candidates.

    Returns list of MetadataCandidate sorted by match score.
    Never raises — returns empty list on failure.
    """
    _ensure_mb_init(user_agent)

    try:
        result = musicbrainzngs.search_recordings(
            artist=artist,
            recording=title,
            limit=limit,
        )
    except Exception:
        logger.warning("MusicBrainz search failed for '%s - %s'", artist, title)
        return []

    candidates: list[MetadataCandidate] = []
    for rec in result.get("recording-list", []):
        rec_title = rec.get("title", "")
        score = float(rec.get("ext:score", 0))
        mb_id = rec.get("id")

        # Artist from artist-credit
        artist_credits = rec.get("artist-credit", [])
        rec_artist = ""
        if artist_credits and isinstance(artist_credits[0], dict):
            rec_artist = artist_credits[0].get("artist", {}).get("name", "")

        # Release (album) info
        releases = rec.get("release-list", [])
        album: str | None = None
        year: int | None = None
        release_id: str | None = None
        if releases:
            first_release = releases[0]
            album = first_release.get("title")
            year = _extract_year(first_release.get("date"))
            release_id = first_release.get("id")

        # Tags
        tag_list = rec.get("tag-list", [])
        genre_tags = [t["name"] for t in tag_list if "name" in t]

        # Label (requires separate lookup per release)
        label: str | None = None
        if release_id:
            label = _get_label_for_release(release_id)

        # Cover art URL
        cover_art_url: str | None = None
        if release_id:
            cover_art_url = f"https://coverartarchive.org/release/{release_id}/front-250"

        candidates.append(
            MetadataCandidate(
                source="musicbrainz",
                artist=rec_artist,
                title=rec_title,
                album=album,
                label=label,
                year=year,
                genre_tags=genre_tags,
                match_score=score,
                musicbrainz_id=mb_id,
                cover_art_url=cover_art_url,
            )
        )

    return candidates
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata_lookup.py -v`
Expected: All 3 tests PASS.

**Step 5: Run type check**

Run: `uv run mypy server/metadata_lookup.py`
Expected: PASS.

**Step 6: Commit**

```bash
git add server/metadata_lookup.py tests/test_metadata_lookup.py
git commit -m "feat(lookup): add MetadataCandidate and MusicBrainz search"
```

---

### Task 4: Build Last.fm Search Function

**Files:**
- Modify: `server/metadata_lookup.py` (add search_lastfm)
- Modify: `tests/test_metadata_lookup.py` (add Last.fm tests)

**Reference:** `docs/references/lastfm-api.md` — Search for Tracks, Get Top Tags, Get Track Info sections

**Step 1: Write Last.fm search tests**

Add to `tests/test_metadata_lookup.py`:

```python
from server.metadata_lookup import search_lastfm


def test_search_lastfm_returns_candidates() -> None:
    mock_track = MagicMock()
    mock_track.get_name.return_value = "Rumble"
    mock_track.artist.get_name.return_value = "Skrillex"

    mock_album = MagicMock()
    mock_album.get_name.return_value = "Quest For Fire"

    mock_tag1 = MagicMock()
    mock_tag1.item.name = "dubstep"
    mock_tag1.weight = 100
    mock_tag2 = MagicMock()
    mock_tag2.item.name = "electronic"
    mock_tag2.weight = 80

    with patch("server.metadata_lookup.pylast") as mock_pylast:
        mock_network = MagicMock()
        mock_pylast.LastFMNetwork.return_value = mock_network
        mock_track_obj = MagicMock()
        mock_network.get_track.return_value = mock_track_obj
        mock_track_obj.get_top_tags.return_value = [mock_tag1, mock_tag2]
        mock_track_obj.get_album.return_value = mock_album

        results = search_lastfm("Skrillex", "Rumble", api_key="test-key")

    assert len(results) == 1
    c = results[0]
    assert c.source == "lastfm"
    assert c.artist == "Skrillex"
    assert c.title == "Rumble"
    assert "dubstep" in c.genre_tags
    assert "electronic" in c.genre_tags


def test_search_lastfm_skipped_without_api_key() -> None:
    results = search_lastfm("Skrillex", "Rumble", api_key="")
    assert results == []


def test_search_lastfm_handles_api_error() -> None:
    with patch("server.metadata_lookup.pylast") as mock_pylast:
        mock_pylast.LastFMNetwork.side_effect = Exception("API error")
        results = search_lastfm("Skrillex", "Rumble", api_key="test-key")

    assert results == []


def test_search_lastfm_handles_no_album() -> None:
    with patch("server.metadata_lookup.pylast") as mock_pylast:
        mock_network = MagicMock()
        mock_pylast.LastFMNetwork.return_value = mock_network
        mock_track_obj = MagicMock()
        mock_network.get_track.return_value = mock_track_obj
        mock_track_obj.get_top_tags.return_value = []
        mock_track_obj.get_album.return_value = None

        results = search_lastfm("Unknown", "Track", api_key="test-key")

    assert len(results) == 1
    assert results[0].album is None
    assert results[0].genre_tags == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_lookup.py::test_search_lastfm_returns_candidates -v`
Expected: FAIL — `ImportError: cannot import name 'search_lastfm'`

**Step 3: Implement search_lastfm**

Add to `server/metadata_lookup.py`:

```python
import pylast  # type: ignore[import-untyped]


def search_lastfm(
    artist: str,
    title: str,
    api_key: str = "",
) -> list[MetadataCandidate]:
    """Search Last.fm for track metadata and genre tags.

    Returns a single MetadataCandidate with genre tags from top tags.
    Returns empty list if no API key or on failure.
    Never raises.
    """
    if not api_key:
        return []

    try:
        network = pylast.LastFMNetwork(api_key=api_key)
        track = network.get_track(artist, title)

        # Get top tags (genre data)
        top_tags = track.get_top_tags()
        genre_tags = [tag_item.item.name for tag_item in top_tags if tag_item.item]

        # Get album info
        album_obj = track.get_album()
        album_name: str | None = None
        if album_obj:
            album_name = album_obj.get_name()

        return [
            MetadataCandidate(
                source="lastfm",
                artist=artist,
                title=title,
                album=album_name,
                genre_tags=genre_tags,
                match_score=100.0,  # Direct lookup, not a search
            )
        ]
    except Exception:
        logger.warning("Last.fm lookup failed for '%s - %s'", artist, title)
        return []
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata_lookup.py -v`
Expected: All tests PASS (MusicBrainz + Last.fm tests).

**Step 5: Run type check**

Run: `uv run mypy server/metadata_lookup.py`
Expected: PASS.

**Step 6: Commit**

```bash
git add server/metadata_lookup.py tests/test_metadata_lookup.py
git commit -m "feat(lookup): add Last.fm search with genre tags"
```

---

### Task 5: Build Combined search_metadata Orchestrator

**Files:**
- Modify: `server/metadata_lookup.py` (add async search_metadata with remix handling)
- Modify: `tests/test_metadata_lookup.py` (add orchestrator tests)

**Step 1: Write orchestrator tests**

Add to `tests/test_metadata_lookup.py`:

```python
import asyncio

from server.metadata_lookup import search_metadata


def test_search_metadata_combines_sources() -> None:
    mb_candidate = MetadataCandidate(
        source="musicbrainz", artist="Skrillex", title="Rumble",
        album="Quest For Fire", match_score=95.0,
    )
    lastfm_candidate = MetadataCandidate(
        source="lastfm", artist="Skrillex", title="Rumble",
        genre_tags=["dubstep", "electronic"], match_score=100.0,
    )

    with (
        patch("server.metadata_lookup.search_musicbrainz", return_value=[mb_candidate]),
        patch("server.metadata_lookup.search_lastfm", return_value=[lastfm_candidate]),
    ):
        results = asyncio.run(search_metadata(
            "Skrillex", "Rumble", lastfm_api_key="key", search_limit=5,
        ))

    assert len(results) == 2
    # Sorted by match_score descending
    assert results[0].source == "lastfm"
    assert results[1].source == "musicbrainz"


def test_search_metadata_handles_remix_title() -> None:
    """Remix titles should trigger additional search queries."""
    captured_calls: list[tuple[str, str]] = []

    def fake_mb_search(artist: str, title: str, **kwargs: object) -> list[MetadataCandidate]:
        captured_calls.append((artist, title))
        return []

    with (
        patch("server.metadata_lookup.search_musicbrainz", side_effect=fake_mb_search),
        patch("server.metadata_lookup.search_lastfm", return_value=[]),
    ):
        asyncio.run(search_metadata(
            "Skrillex", "Rumble (Fred again.. Remix)",
            lastfm_api_key="key", search_limit=5,
        ))

    # Should search for both the full title and a stripped version
    titles_searched = [call[1] for call in captured_calls]
    assert any("Fred again" in t for t in titles_searched)


def test_search_metadata_returns_empty_on_all_failures() -> None:
    with (
        patch("server.metadata_lookup.search_musicbrainz", return_value=[]),
        patch("server.metadata_lookup.search_lastfm", return_value=[]),
    ):
        results = asyncio.run(search_metadata(
            "Unknown", "Track", lastfm_api_key="", search_limit=5,
        ))

    assert results == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_lookup.py::test_search_metadata_combines_sources -v`
Expected: FAIL — `ImportError: cannot import name 'search_metadata'`

**Step 3: Implement search_metadata with remix handling**

Add to `server/metadata_lookup.py`:

```python
import asyncio
import re

_REMIX_RE = re.compile(
    r"\(([^)]+?)\s+(remix|edit|bootleg|vip|flip)\)",
    re.IGNORECASE,
)


def _parse_remix(title: str) -> tuple[str, str | None]:
    """Extract base title and remix query from a title.

    Returns (base_title, remix_query) where remix_query is None if not a remix.
    Example: "Rumble (Fred again.. Remix)" -> ("Rumble", "Rumble Fred again Remix")
    """
    match = _REMIX_RE.search(title)
    if not match:
        return title, None

    base = title[: match.start()].strip()
    remix_query = f"{base} {match.group(1)} {match.group(2)}"
    return base, remix_query


async def search_metadata(
    artist: str,
    title: str,
    lastfm_api_key: str = "",
    search_limit: int = 5,
    user_agent: str = "dj-kompanion/1.0",
) -> list[MetadataCandidate]:
    """Search MusicBrainz + Last.fm for metadata candidates.

    Runs both searches in parallel via asyncio.to_thread.
    Returns combined list sorted by match_score descending.
    Never raises — returns empty list on failure.
    """
    base_title, remix_query = _parse_remix(title)

    async def _mb_search() -> list[MetadataCandidate]:
        results = await asyncio.to_thread(
            search_musicbrainz, artist, title, search_limit, user_agent,
        )
        # If remix, also search with remix query for better coverage
        if remix_query:
            extra = await asyncio.to_thread(
                search_musicbrainz, artist, remix_query, search_limit, user_agent,
            )
            # Deduplicate by musicbrainz_id
            seen_ids = {c.musicbrainz_id for c in results if c.musicbrainz_id}
            for c in extra:
                if c.musicbrainz_id not in seen_ids:
                    results.append(c)
                    seen_ids.add(c.musicbrainz_id)
        return results

    async def _lastfm_search() -> list[MetadataCandidate]:
        return await asyncio.to_thread(
            search_lastfm, artist, title, lastfm_api_key,
        )

    mb_results, lastfm_results = await asyncio.gather(
        _mb_search(), _lastfm_search(),
    )

    combined = mb_results + lastfm_results
    combined.sort(key=lambda c: c.match_score, reverse=True)
    return combined
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata_lookup.py -v`
Expected: All tests PASS.

**Step 5: Run type check**

Run: `uv run mypy server/metadata_lookup.py`
Expected: PASS.

**Step 6: Commit**

```bash
git add server/metadata_lookup.py tests/test_metadata_lookup.py
git commit -m "feat(lookup): add combined search_metadata with remix handling"
```

---

### Task 6: Update Claude Prompt for Candidate Selection

**Files:**
- Modify: `server/enrichment.py` (new prompt template, new response parsing)
- Modify: `tests/test_enrichment.py` (tests for new prompt flow)

**Step 1: Write tests for the new prompt-with-candidates flow**

Add to `tests/test_enrichment.py`:

```python
from server.metadata_lookup import MetadataCandidate


def claude_json_with_candidates(
    artist: str = "Skrillex",
    title: str = "Rumble",
    album: str | None = "Quest For Fire",
    genre: str | None = "dubstep",
    year: int | None = 2023,
    label: str | None = "OWSLA",
    energy: int | None = 8,
    selected_candidate_index: int | None = 0,
    confidence: str = "high",
    cover_art_url: str | None = None,
    comment: str = "https://youtube.com/watch?v=test",
) -> str:
    data: dict[str, Any] = {
        "selected_candidate_index": selected_candidate_index,
        "confidence": confidence,
        "artist": artist,
        "title": title,
        "album": album,
        "genre": genre,
        "year": year,
        "label": label,
        "energy": energy,
        "bpm": None,
        "key": None,
        "comment": comment,
        "cover_art_url": cover_art_url,
    }
    return json.dumps(data)


def test_enrich_with_candidates_selects_match() -> None:
    raw = make_raw(title="Skrillex - Rumble (Official Video)")
    candidates = [
        MetadataCandidate(
            source="musicbrainz", artist="Skrillex", title="Rumble",
            album="Quest For Fire", label="OWSLA", year=2023,
            genre_tags=["dubstep", "electronic"], match_score=95.0,
            cover_art_url="https://coverartarchive.org/release/abc/front-250",
        ),
    ]
    response = claude_json_with_candidates(
        cover_art_url="https://coverartarchive.org/release/abc/front-250",
    )

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(enrich_metadata(raw, candidates=candidates))

    assert result.artist == "Skrillex"
    assert result.album == "Quest For Fire"
    assert result.genre == "dubstep"
    assert result.label == "OWSLA"
    assert result.year == 2023
    assert result.cover_art_url == "https://coverartarchive.org/release/abc/front-250"


def test_enrich_with_candidates_no_match_falls_back_to_inference() -> None:
    raw = make_raw(title="Unknown Artist - Rare Track")
    candidates = [
        MetadataCandidate(
            source="musicbrainz", artist="Different Artist", title="Different Song",
            match_score=30.0,
        ),
    ]
    response = claude_json_with_candidates(
        artist="Unknown Artist", title="Rare Track",
        selected_candidate_index=None, confidence="low",
        album=None, label=None, year=None, genre="electronic",
    )

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(enrich_metadata(raw, candidates=candidates))

    assert result.artist == "Unknown Artist"
    assert result.genre == "electronic"  # LLM inferred
    assert result.album is None  # No API match


def test_enrich_with_empty_candidates_uses_original_prompt() -> None:
    """When no API candidates, should still work with original inference flow."""
    raw = make_raw(title="Bicep - GLUE")
    response = claude_json(artist="Bicep", title="GLUE", genre="House")

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(enrich_metadata(raw, candidates=[]))

    assert result.artist == "Bicep"
    assert result.genre == "House"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enrichment.py::test_enrich_with_candidates_selects_match -v`
Expected: FAIL — `enrich_metadata() got an unexpected keyword argument 'candidates'`

**Step 3: Update enrichment.py with new prompt and candidate-aware flow**

Modify `server/enrichment.py`:

1. Add a new prompt template `_PROMPT_WITH_CANDIDATES_TEMPLATE` that includes the candidate selection logic (from the design doc).
2. Update `_parse_claude_response` to handle the new response fields (`selected_candidate_index`, `confidence`, `album`, `cover_art_url`).
3. Update `enrich_metadata` and `try_enrich_metadata` to accept an optional `candidates` parameter.
4. When candidates are provided and non-empty, use the new prompt. When empty, use the existing prompt (backward compatible).

Key implementation details:
- The new prompt template should match the design doc's prompt exactly
- `_parse_claude_response` needs to extract `album` and `cover_art_url` from the response
- The `candidates` parameter should be `list[MetadataCandidate]` (import from metadata_lookup)
- Serialize candidates to JSON for the prompt using a helper function

**Step 4: Run all enrichment tests**

Run: `uv run pytest tests/test_enrichment.py -v`
Expected: All tests PASS (existing + new).

**Step 5: Run type check**

Run: `uv run mypy server/enrichment.py`
Expected: PASS.

**Step 6: Commit**

```bash
git add server/enrichment.py tests/test_enrichment.py
git commit -m "feat(enrichment): update Claude prompt for candidate selection with API results"
```

---

### Task 7: Wire into Download Endpoint (Parallel Execution)

**Files:**
- Modify: `server/app.py` (update download endpoint to run API search + Claude in pipeline)
- Modify: `tests/test_app.py` (if exists, add integration tests)

**Step 1: Write test for the new download flow**

Check if `tests/test_app.py` exists. If not, this test can go in a new file `tests/test_download_flow.py`:

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from server.metadata_lookup import MetadataCandidate


def test_download_uses_api_search_when_enabled() -> None:
    """Verify that the download endpoint calls search_metadata when metadata_lookup is enabled."""
    # This is a flow test — we verify the wiring, not the API calls.
    # The actual API calls are tested in test_metadata_lookup.py.
    # We mock search_metadata and verify it's called with the right args.

    from server.app import download
    from server.models import DownloadRequest, EnrichedMetadata, RawMetadata

    raw = RawMetadata(
        title="Skrillex - Rumble", uploader="Skrillex", duration=180,
        upload_date="20230101", description=None, tags=[], source_url="https://youtube.com/test",
    )
    metadata = EnrichedMetadata(artist="Skrillex", title="Rumble")
    req = DownloadRequest(url="https://youtube.com/test", metadata=metadata, raw=raw, format="best")

    # This test verifies wiring — actual implementation details in Task 7 Step 3.
    # The key assertion is that search_metadata is called when config.metadata_lookup.enabled is True.
```

Note: The exact test structure depends on how the existing `tests/test_app.py` is organized. The subagent implementing this task should read the existing test patterns and follow them. The critical behavior to test:

1. When `metadata_lookup.enabled` is True and Claude is available: `search_metadata` runs in parallel with `download_audio`, then Claude gets the candidates.
2. When `metadata_lookup.enabled` is False: current behavior unchanged.
3. When `search_metadata` returns empty list: Claude still runs with original prompt.
4. `enrichment_source` is set to `"api+claude"` when API candidates contributed to the result.

**Step 2: Update the download endpoint**

In `server/app.py`, modify the `download` function:

The key change is in the `use_llm` branch. Currently it runs:
```python
results = await asyncio.gather(
    download_audio(...),
    try_enrich_metadata(req.raw, model=cfg.llm.model),
    return_exceptions=True,
)
```

The new flow:
```python
# Step 1: Run download + API search in parallel
dl_task = download_audio(req.url, cfg.output_dir, filename, req.format, cookies=req.cookies)

if cfg.metadata_lookup.enabled:
    search_artist = basic_enriched.artist
    search_title = basic_enriched.title
    api_task = search_metadata(
        search_artist, search_title,
        lastfm_api_key=cfg.metadata_lookup.lastfm_api_key,
        search_limit=cfg.metadata_lookup.search_limit,
        user_agent=cfg.metadata_lookup.musicbrainz_user_agent,
    )
else:
    api_task = asyncio.coroutine(lambda: [])()  # empty coroutine

# Run download + API search concurrently
filepath_result, candidates = await asyncio.gather(dl_task, api_task, return_exceptions=True)

# Handle download errors (same as before)...

# Step 2: Run Claude with candidates
if isinstance(candidates, BaseException):
    candidates = []

claude_result = await try_enrich_metadata(req.raw, model=cfg.llm.model, candidates=candidates)

# Step 3: Set enrichment_source based on what contributed
if claude_result is not None and candidates:
    enrichment_source = "api+claude"
elif claude_result is not None:
    enrichment_source = "claude"
else:
    enrichment_source = "basic"
```

Important: The subagent should also call `basic_enrich(req.raw)` early to get the cleaned artist+title for the API search query. This is already available from the preview step, but we need it at download time too for the search.

**Step 3: Add search_metadata import**

Add to `server/app.py` imports:

```python
from server.metadata_lookup import search_metadata
```

**Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS.

**Step 5: Run type check**

Run: `uv run mypy server/`
Expected: PASS.

**Step 6: Commit**

```bash
git add server/app.py
git commit -m "feat(download): wire API search into download pipeline with parallel execution"
```

---

### Task 8: Update TypeScript Types in Extension

**Files:**
- Modify: `extension/src/types.ts` (add album, cover_art_url, update enrichment_source)

**Step 1: Update EnrichedMetadata interface**

In `extension/src/types.ts`, add the new fields:

```typescript
export interface EnrichedMetadata {
  artist: string;
  title: string;
  album: string | null;  // NEW
  genre: string | null;
  year: number | null;
  label: string | null;
  energy: number | null;
  bpm: number | null;
  key: string | null;
  cover_art_url: string | null;  // NEW
  comment: string;
}
```

**Step 2: Update DownloadResponse enrichment_source**

```typescript
export interface DownloadResponse {
  status: string;
  filepath: string;
  enrichment_source: "api+claude" | "claude" | "basic" | "none";  // UPDATED
  metadata?: EnrichedMetadata;
}
```

**Step 3: Update QueueItem enrichmentSource**

```typescript
export interface QueueItem {
  // ... existing fields ...
  enrichmentSource?: "api+claude" | "claude" | "basic" | "none";  // UPDATED
  // ...
}
```

**Step 4: Type check the extension**

Run: `cd extension && npx tsc --noEmit`
Expected: May produce errors if popup.ts or background.ts reference EnrichedMetadata fields that need updating. Fix any type errors by adding the new fields where EnrichedMetadata objects are constructed.

**Step 5: Build the extension**

Run: `cd extension && npm run build`
Expected: PASS.

**Step 6: Commit**

```bash
git add extension/src/types.ts
# Also add any other extension files that needed updating
git commit -m "feat(extension): add album, cover_art_url types and api+claude enrichment source"
```

---

### Task 9: Integration Test — Full Download Flow with Mocked APIs

**Files:**
- Create or modify: `tests/test_integration.py`

**Step 1: Write integration test**

This test exercises the full flow: download endpoint receives a request, API search runs (mocked), Claude enrichment runs (mocked), results are merged, and the response includes the correct enrichment_source.

```python
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app
from server.metadata_lookup import MetadataCandidate


@pytest.fixture
def mock_config() -> Any:
    """Return a config with metadata_lookup enabled."""
    from server.config import AnalysisConfig, AppConfig, LLMConfig, MetadataLookupConfig

    return AppConfig(
        llm=LLMConfig(enabled=True),
        analysis=AnalysisConfig(enabled=False),
        metadata_lookup=MetadataLookupConfig(
            enabled=True, lastfm_api_key="test-key", search_limit=5,
        ),
    )


@pytest.mark.asyncio
async def test_download_with_api_enrichment(mock_config: Any, tmp_path: Any) -> None:
    """Full integration: download + API search + Claude enrichment."""
    mock_config.output_dir = tmp_path

    candidates = [
        MetadataCandidate(
            source="musicbrainz", artist="Skrillex", title="Rumble",
            album="Quest For Fire", label="OWSLA", year=2023,
            genre_tags=["dubstep"], match_score=95.0,
            cover_art_url="https://coverartarchive.org/release/abc/front-250",
        ),
    ]

    claude_response = json.dumps({
        "selected_candidate_index": 0,
        "confidence": "high",
        "artist": "Skrillex",
        "title": "Rumble",
        "album": "Quest For Fire",
        "genre": "dubstep",
        "year": 2023,
        "label": "OWSLA",
        "energy": 8,
        "bpm": None,
        "key": None,
        "comment": "https://youtube.com/test",
        "cover_art_url": "https://coverartarchive.org/release/abc/front-250",
    })

    # Mock all external dependencies
    with (
        patch("server.app.load_config", return_value=mock_config),
        patch("server.app.download_audio", return_value=tmp_path / "test.mp3"),
        patch("server.app.search_metadata", return_value=candidates),
        patch("server.app.is_claude_available", return_value=True),
        patch("server.app.try_enrich_metadata") as mock_enrich,
        patch("server.app.tag_file", return_value=tmp_path / "Skrillex - Rumble.mp3"),
    ):
        from server.models import EnrichedMetadata

        mock_enrich.return_value = EnrichedMetadata(
            artist="Skrillex", title="Rumble", album="Quest For Fire",
            genre="dubstep", year=2023, label="OWSLA", energy=8,
            cover_art_url="https://coverartarchive.org/release/abc/front-250",
            comment="https://youtube.com/test",
        )

        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/download", json={
                "url": "https://youtube.com/test",
                "metadata": {"artist": "Skrillex", "title": "Rumble", "comment": ""},
                "raw": {
                    "title": "Skrillex - Rumble (Official Video)",
                    "uploader": "Skrillex", "duration": 180,
                    "upload_date": "20230101", "description": None,
                    "tags": [], "source_url": "https://youtube.com/test",
                },
                "format": "best",
                "user_edited_fields": [],
            })

    assert resp.status_code == 200
    data = resp.json()
    assert data["enrichment_source"] == "api+claude"
    assert data["metadata"]["album"] == "Quest For Fire"
    assert data["metadata"]["genre"] == "dubstep"
```

**Step 2: Run integration test**

Run: `uv run pytest tests/test_integration.py -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for API-enriched download flow"
```

---

### Task 10: Lint, Type-Check, and Final Verification

**Files:** All modified files

**Step 1: Run linter**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS (or fix any issues).

If ruff reports issues, fix them:
Run: `uv run ruff check --fix . && uv run ruff format .`

**Step 2: Run type checker**

Run: `uv run mypy server/`
Expected: PASS with no errors.

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS.

**Step 4: Run extension type check**

Run: `cd extension && npx tsc --noEmit`
Expected: PASS.

**Step 5: Verify extension builds**

Run: `cd extension && npm run build`
Expected: PASS.

**Step 6: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "chore: lint and type-check fixes for metadata API enrichment"
```

---

## Outcomes & Retrospective

**What worked:**
- Search-then-Select architecture cleanly separates API lookup from LLM reasoning — each does what it's best at
- Parallel execution (download + API search) adds zero wall-clock time to the download flow
- Agent team orchestration with 10 tasks completed smoothly; parallel waves (Tasks 1+2, 3+8) saved time
- Reference docs (`docs/references/musicbrainz-api.md`, `docs/references/lastfm-api.md`) gave workers concrete API guidance, reducing trial-and-error
- Remix-aware search (`_parse_remix`) handles the common DJ use case of "Song (Remixer Remix)" titles

**What didn't:**
- musicbrainzngs mypy override `follow_imports = "skip"` in pyproject.toml doesn't suppress `import-untyped` on bare imports — needed inline `# type: ignore` anyway
- Workers' code wasn't always ruff-formatted — Task 10 had to apply formatting to 4 files. Could enforce `ruff format --check` in worker acceptance criteria.
- Existing app tests broke when `metadata_lookup.enabled` defaults to True — required retroactive mocking of `search_metadata` in 3 existing tests

**Learnings to codify:**
- For untyped libraries, always add both pyproject.toml mypy override AND inline `# type: ignore[import-untyped]` on the import line
- When adding new config that defaults to enabled, check existing tests that mock the config — they'll need the new mock too
- pylast has type stubs; musicbrainzngs does not — verify before assuming both need `type: ignore`
