# Deferred Enrichment Implementation Plan

> **Status**: Complete | **Created**: 2026-02-26 | **Last Updated**: 2026-02-26
> **Design Doc**: Plan derived from brainstorming session (no separate design doc)
> **For Claude:** Use /harness:orchestrate to execute this plan.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move Claude enrichment from preview (blocking, slow) to download (parallel with yt-dlp, zero extra wall-clock time), with smart user-edit tracking.

**Architecture:** Preview uses `basic_enrich` only (instant). Download kicks off yt-dlp + Claude enrichment concurrently via `asyncio.gather`. A new `merge_metadata` function combines user edits, Claude results, and basic fallbacks with user-edit priority.

**Tech Stack:** Python/FastAPI (server), TypeScript (extension), Pydantic models, asyncio

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-02-26 | Design | Only fill blanks by default, track user edits | User explicitly edited fields should never be overwritten by Claude |
| 2026-02-26 | Design | Run enrichment parallel with download | Download takes several seconds anyway; Claude runs in parallel at zero extra cost |
| 2026-02-26 | Design | Add `try_enrich_metadata` (returns None on failure) | Keeps existing `enrich_metadata` unchanged for CLI; lets download endpoint distinguish success vs failure |
| 2026-02-26 | Design | Pass `raw` in DownloadRequest | Avoids redundant yt-dlp metadata extraction during download; extension already has raw from preview |

## Progress

- [x] Task 1: Update Pydantic models
- [x] Task 2: Add `merge_metadata` to enrichment
- [x] Task 3: Add `try_enrich_metadata` to enrichment
- [x] Task 4: Simplify preview endpoint
- [x] Task 5: Restructure download endpoint
- [x] Task 6: Update TypeScript types
- [x] Task 7: Add edit tracking to popup
- [x] Task 8: Reduce preview timeout
- [x] Task 9: Update existing tests
- [x] Task 10: Final verification

## Surprises & Discoveries

- `cast("Path", filepath_result)` was redundant — mypy already narrowed the type after isinstance checks, removed it
- ruff SIM114 flagged combining `comment` and `user_edited_fields` branches in merge_metadata — applied

## Plan Drift

_None yet — updated when tasks deviate from plan during execution._

---

### Task 1: Update Pydantic Models

**Files:**
- Modify: `server/models.py`

**Step 1: Add `raw` and `user_edited_fields` to `DownloadRequest`, `enrichment_source` to `DownloadResponse`**

```python
# In DownloadRequest, add after format field:
class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    raw: RawMetadata
    format: str = "best"
    user_edited_fields: list[str] = []

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in _ALLOWED_FORMATS:
            msg = f"format must be one of {sorted(_ALLOWED_FORMATS)}"
            raise ValueError(msg)
        return v


# Replace DownloadResponse:
class DownloadResponse(BaseModel):
    status: str
    filepath: str
    enrichment_source: Literal["claude", "basic", "none"] = "none"
```

**Step 2: Run type check**

Run: `uv run mypy server/models.py`
Expected: PASS

**Step 3: Commit**

```bash
git add server/models.py
git commit -m "feat(models): add raw, user_edited_fields to DownloadRequest; enrichment_source to DownloadResponse"
```

---

### Task 2: Add `merge_metadata` to Enrichment

**Files:**
- Modify: `server/enrichment.py`
- Modify: `tests/test_enrichment.py`

**Step 1: Write failing tests for `merge_metadata`**

Add to bottom of `tests/test_enrichment.py`:

```python
from server.enrichment import merge_metadata


def test_merge_user_edited_wins_over_claude() -> None:
    user = EnrichedMetadata(artist="My Edit", title="My Title", genre="Pop")
    claude = EnrichedMetadata(artist="Claude Artist", title="Claude Title", genre="EDM")
    result = merge_metadata(user, claude, user_edited_fields=["artist", "genre"])
    assert result.artist == "My Edit"  # user edited
    assert result.genre == "Pop"  # user edited
    assert result.title == "Claude Title"  # not edited, Claude wins


def test_merge_claude_fills_non_edited_nulls() -> None:
    user = EnrichedMetadata(artist="Artist", title="Title", genre=None)
    claude = EnrichedMetadata(artist="Artist", title="Title", genre="House", year=2024, energy=7)
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.genre == "House"
    assert result.year == 2024
    assert result.energy == 7


def test_merge_basic_fallback_for_claude_null() -> None:
    user = EnrichedMetadata(artist="Artist", title="Title", energy=5)
    claude = EnrichedMetadata(artist="Artist", title="Title", energy=None)
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.energy == 5  # Claude null, fall back to user/basic value


def test_merge_none_claude_returns_basic() -> None:
    user = EnrichedMetadata(artist="Artist", title="Title", genre="Pop")
    result = merge_metadata(user, None, user_edited_fields=[])
    assert result.artist == "Artist"
    assert result.genre == "Pop"


def test_merge_empty_edited_uses_all_claude() -> None:
    user = EnrichedMetadata(artist="Basic", title="Basic")
    claude = EnrichedMetadata(
        artist="Claude", title="Better Title", genre="Techno", year=2023, energy=8
    )
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.artist == "Claude"
    assert result.title == "Better Title"
    assert result.genre == "Techno"
    assert result.year == 2023
    assert result.energy == 8


def test_merge_preserves_comment() -> None:
    user = EnrichedMetadata(artist="A", title="T", comment="https://example.com")
    claude = EnrichedMetadata(artist="A", title="T", comment="https://other.com")
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.comment == "https://example.com"  # user's comment always preserved
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enrichment.py -k merge -v`
Expected: FAIL with ImportError (merge_metadata doesn't exist yet)

**Step 3: Implement `merge_metadata`**

Add to `server/enrichment.py` after `basic_enrich`:

```python
def merge_metadata(
    user: EnrichedMetadata,
    claude: EnrichedMetadata | None,
    user_edited_fields: list[str],
) -> EnrichedMetadata:
    """Merge user-edited metadata with Claude enrichment results.

    Priority: user-edited fields > Claude non-null > user/basic value.
    Comment is always preserved from the user's metadata.
    """
    if claude is None:
        return user

    user_dict = user.model_dump()
    claude_dict = claude.model_dump()

    merged: dict[str, object] = {}
    for field, user_val in user_dict.items():
        if field == "comment":
            merged[field] = user_val
        elif field in user_edited_fields:
            merged[field] = user_val
        elif claude_dict[field] is not None:
            merged[field] = claude_dict[field]
        else:
            merged[field] = user_val

    return EnrichedMetadata.model_validate(merged)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_enrichment.py -k merge -v`
Expected: All 6 PASS

**Step 5: Run mypy**

Run: `uv run mypy server/enrichment.py`
Expected: PASS

**Step 6: Commit**

```bash
git add server/enrichment.py tests/test_enrichment.py
git commit -m "feat(enrichment): add merge_metadata for smart user-edit-aware merging"
```

---

### Task 3: Add `try_enrich_metadata` to Enrichment

**Files:**
- Modify: `server/enrichment.py`
- Modify: `tests/test_enrichment.py`

**Step 1: Write failing tests**

Add to `tests/test_enrichment.py`:

```python
from server.enrichment import try_enrich_metadata


def test_try_enrich_returns_none_when_unavailable() -> None:
    raw = make_raw()
    with patch("server.enrichment.subprocess.run", side_effect=FileNotFoundError()):
        result = asyncio.run(try_enrich_metadata(raw))
    assert result is None


def test_try_enrich_returns_none_on_timeout() -> None:
    raw = make_raw()

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        raise subprocess.TimeoutExpired("claude", 30)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(try_enrich_metadata(raw))
    assert result is None


def test_try_enrich_returns_metadata_on_success() -> None:
    raw = make_raw()
    response = claude_json(artist="Bicep", title="GLUE", genre="Electronic")

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(try_enrich_metadata(raw))

    assert result is not None
    assert result.artist == "Bicep"
    assert result.genre == "Electronic"


def test_try_enrich_returns_none_on_invalid_json() -> None:
    raw = make_raw()

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        return make_process("not json", returncode=0)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(try_enrich_metadata(raw))
    assert result is None
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_enrichment.py -k try_enrich -v`
Expected: FAIL with ImportError

**Step 3: Implement `try_enrich_metadata`**

Add to `server/enrichment.py` after `enrich_metadata`:

```python
async def try_enrich_metadata(raw: RawMetadata, model: str = "haiku") -> EnrichedMetadata | None:
    """Like enrich_metadata, but returns None instead of falling back.

    Used by the download endpoint to distinguish Claude success from failure.
    """
    if not await is_claude_available():
        return None

    prompt = _PROMPT_TEMPLATE.format(
        raw_metadata_json=raw.model_dump_json(indent=2),
    )

    cmd = ["claude", "-p", "--model", model, "--output-format", "json", prompt]

    try:
        result = await asyncio.to_thread(_run_subprocess, cmd, 30.0)
    except subprocess.TimeoutExpired:
        logger.warning("claude timed out after 30s")
        return None
    except (FileNotFoundError, OSError) as e:
        logger.warning("claude CLI error: %s", e)
        return None

    if result.returncode != 0:
        logger.warning("claude returned non-zero exit code %d", result.returncode)
        return None

    return _parse_claude_response(result.stdout, raw)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_enrichment.py -k try_enrich -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add server/enrichment.py tests/test_enrichment.py
git commit -m "feat(enrichment): add try_enrich_metadata returning None on failure"
```

---

### Task 4: Simplify Preview Endpoint

**Files:**
- Modify: `server/app.py`

**Step 1: Replace preview endpoint**

Change the preview function in `server/app.py` to:

```python
@app.post("/api/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest) -> PreviewResponse:
    try:
        raw = await extract_metadata(req.url)
    except DownloadError as e:
        raise HTTPException(
            status_code=404,
            detail={"error": "extraction_failed", "message": e.message, "url": e.url},
        ) from e

    enriched = basic_enrich(raw)
    return PreviewResponse(raw=raw, enriched=enriched, enrichment_source="none")
```

Update imports at top of `server/app.py`:
- Remove `enrich_metadata` from import (no longer used in preview)
- Add `basic_enrich` to import from `server.enrichment`
- Keep `is_claude_available` (still needed by health endpoint)

New import line:
```python
from server.enrichment import basic_enrich, is_claude_available
```

**Step 2: Run mypy and ruff**

Run: `uv run mypy server/app.py && uv run ruff check server/app.py`
Expected: PASS

**Step 3: Commit**

```bash
git add server/app.py
git commit -m "feat(preview): use basic_enrich only, remove Claude from preview path"
```

---

### Task 5: Restructure Download Endpoint

**Files:**
- Modify: `server/app.py`

**Step 1: Update imports**

```python
import asyncio
from pathlib import Path
from typing import Any, Literal, cast

from server.enrichment import basic_enrich, is_claude_available, merge_metadata, try_enrich_metadata
```

**Step 2: Replace download endpoint**

```python
@app.post("/api/download", response_model=DownloadResponse)
async def download(req: DownloadRequest) -> DownloadResponse:
    cfg = load_config()

    filename = build_download_filename(req.metadata.artist, req.metadata.title)
    use_llm = cfg.llm.enabled and await is_claude_available()

    enrichment_source: Literal["claude", "basic", "none"]

    if use_llm:
        results = await asyncio.gather(
            download_audio(req.url, cfg.output_dir, filename, req.format),
            try_enrich_metadata(req.raw, model=cfg.llm.model),
            return_exceptions=True,
        )
        filepath_result, claude_result = results

        if isinstance(filepath_result, DownloadError):
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "download_failed",
                    "message": filepath_result.message,
                    "url": filepath_result.url,
                },
            ) from filepath_result
        if isinstance(filepath_result, BaseException):
            raise HTTPException(
                status_code=500,
                detail={"error": "download_failed", "message": str(filepath_result), "url": req.url},
            ) from filepath_result

        filepath = cast("Path", filepath_result)

        if isinstance(claude_result, BaseException) or claude_result is None:
            final_metadata = merge_metadata(req.metadata, basic_enrich(req.raw), req.user_edited_fields)
            enrichment_source = "basic"
        else:
            final_metadata = merge_metadata(req.metadata, claude_result, req.user_edited_fields)
            enrichment_source = "claude"
    else:
        try:
            filepath = await download_audio(req.url, cfg.output_dir, filename, req.format)
        except DownloadError as e:
            raise HTTPException(
                status_code=500,
                detail={"error": "download_failed", "message": e.message, "url": e.url},
            ) from e
        final_metadata = req.metadata
        enrichment_source = "none"

    try:
        final_path = tag_file(filepath, final_metadata)
    except TaggingError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "tagging_failed",
                "message": e.message,
                "filepath": str(e.filepath),
            },
        ) from e

    return DownloadResponse(
        status="complete",
        filepath=str(final_path),
        enrichment_source=enrichment_source,
    )
```

**Step 3: Run mypy and ruff**

Run: `uv run mypy server/app.py && uv run ruff check server/app.py`
Expected: PASS

**Step 4: Commit**

```bash
git add server/app.py
git commit -m "feat(download): parallel download+enrichment with smart merge"
```

---

### Task 6: Update TypeScript Types

**Files:**
- Modify: `extension/src/types.ts`

**Step 1: Update interfaces**

```typescript
export interface DownloadRequest {
  url: string;
  metadata: EnrichedMetadata;
  raw: RawMetadata;
  format: string;
  user_edited_fields: string[];
}

export interface DownloadResponse {
  status: string;
  filepath: string;
  enrichment_source: "claude" | "basic" | "none";
}
```

**Step 2: Run type check**

Run: `cd extension && npx tsc --noEmit`
Expected: FAIL (popup.ts doesn't pass `raw`/`user_edited_fields` yet — that's expected, Task 7 fixes it)

**Step 3: Commit** (skip until Task 7 completes — commit together)

---

### Task 7: Add Edit Tracking to Popup

**Files:**
- Modify: `extension/src/popup.ts`

**Step 1: Add state variables and import**

At the top of `popup.ts`, update imports and add state:

```typescript
import { fetchPreview, healthCheck, requestDownload } from "./api.js";
import { getEl } from "./dom.js";
import type { DownloadRequest, EnrichedMetadata, RawMetadata } from "./types.js";

type PopupState = "initial" | "loading" | "preview" | "downloading" | "complete" | "error";

let currentUrl = "";
let lastErrorMessage = "";
let initialMetadata: EnrichedMetadata | null = null;
let previewRaw: RawMetadata | null = null;
```

**Step 2: Add `computeUserEditedFields`**

After `getSelectedFormat()`:

```typescript
function computeUserEditedFields(current: EnrichedMetadata): string[] {
  if (initialMetadata === null) return [];

  const fields: Array<keyof EnrichedMetadata> = [
    "artist", "title", "genre", "year", "label", "energy", "bpm", "key", "comment",
  ];

  return fields.filter((field) => {
    const initial = initialMetadata![field];
    const now = current[field];
    return String(initial ?? "") !== String(now ?? "");
  });
}
```

**Step 3: Update `init()` to reset state**

Add at the top of `init()`:

```typescript
async function init(): Promise<void> {
  initialMetadata = null;
  previewRaw = null;
  // ... rest unchanged
```

**Step 4: Update `handleFetchMetadata` to save snapshots**

```typescript
async function handleFetchMetadata(): Promise<void> {
  const btn = getEl<HTMLButtonElement>("btn-fetch");
  btn.disabled = true;
  render("loading");

  try {
    const preview = await fetchPreview(currentUrl);
    populatePreviewForm(preview.enriched, preview.enrichment_source, currentUrl);
    initialMetadata = { ...preview.enriched };
    previewRaw = preview.raw;
    render("preview");
  } catch (err) {
    lastErrorMessage = err instanceof Error ? err.message : String(err);
    const errEl = document.getElementById("error-message");
    if (errEl) errEl.textContent = lastErrorMessage;
    render("error");
  }
}
```

**Step 5: Update `handleDownload` to pass raw and user_edited_fields**

```typescript
async function handleDownload(): Promise<void> {
  const metadata = readMetadataFromForm();
  const format = getSelectedFormat();
  const userEditedFields = computeUserEditedFields(metadata);

  const req: DownloadRequest = {
    url: currentUrl,
    metadata,
    raw: previewRaw!,
    format,
    user_edited_fields: userEditedFields,
  };

  // ... rest unchanged
```

**Step 6: Update enrichment source display text**

In `populatePreviewForm`, update the enrichment badge text since preview always returns "none" now:

```typescript
  const enrichmentEl = document.getElementById("enrichment-source");
  if (enrichmentEl) {
    enrichmentEl.textContent =
      source === "claude" ? "Enriched by Claude" : "Metadata preview";
  }
```

**Step 7: Run type check, lint, build**

Run: `cd extension && npx tsc --noEmit && npx eslint src/ && npm run build`
Expected: PASS

**Step 8: Commit**

```bash
git add extension/src/types.ts extension/src/popup.ts
git commit -m "feat(extension): track user edits, pass raw + edited fields in download"
```

---

### Task 8: Reduce Preview Timeout

**Files:**
- Modify: `extension/src/api.ts`

**Step 1: Change timeout from 30000 to 10000**

In `fetchPreview`, change the timeout parameter:

```typescript
    30000,  // change to:
    10000,
```

**Step 2: Build and verify**

Run: `cd extension && npm run build`
Expected: PASS

**Step 3: Commit**

```bash
git add extension/src/api.ts
git commit -m "feat(api): reduce preview timeout to 10s (no LLM call)"
```

---

### Task 9: Update Existing Tests

**Files:**
- Modify: `tests/test_app.py`

**Step 1: Update test fixtures — add SAMPLE_RAW_DICT**

At the top of `test_app.py`, after SAMPLE_ENRICHED:

```python
SAMPLE_RAW_DICT: dict[str, object] = {
    "title": "DJ Snake - Turn Down for What (Official Video)",
    "uploader": "DJ Snake",
    "duration": 210,
    "upload_date": "20140101",
    "description": "Turn Down for What",
    "tags": ["edm", "electronic"],
    "source_url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
}
```

**Step 2: Update `test_preview_success`**

Replace with:

```python
async def test_preview_success(client: AsyncClient) -> None:
    with patch("server.app.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW):
        response = await client.post(
            "/api/preview", json={"url": "https://www.youtube.com/watch?v=HMUDVMiITOU"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enriched"]["artist"] == "DJ Snake"
    assert data["enrichment_source"] == "none"
    assert "raw" in data
```

**Step 3: Update all download tests to include `raw`**

Update `test_download_success`:

```python
async def test_download_success(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["filepath"] == str(mock_path)
    assert data["enrichment_source"] == "none"
```

Update `test_download_failure`:

```python
async def test_download_failure(client: AsyncClient) -> None:
    with (
        patch(
            "server.app.download_audio",
            new_callable=AsyncMock,
            side_effect=DownloadError("Download failed", url="https://example.com"),
        ),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://example.com",
                "metadata": {"artist": "Test", "title": "Track"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "download_failed"
```

Update `test_download_tagging_failure`:

```python
async def test_download_tagging_failure(client: AsyncClient) -> None:
    from server.tagger import TaggingError

    mock_path = Path("/tmp/download.xyz")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch(
            "server.app.tag_file",
            side_effect=TaggingError("Unsupported format: .xyz", mock_path),
        ),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://example.com",
                "metadata": {"artist": "Test", "title": "Track"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "tagging_failed"
```

**Step 4: Add new download enrichment tests**

```python
async def test_download_with_claude_enrichment(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enrichment_source"] == "claude"


async def test_download_claude_fails_gracefully(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enrichment_source"] == "basic"


async def test_download_user_edited_fields_preserved(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    claude_enriched = EnrichedMetadata(
        artist="Claude Artist", title="Claude Title", genre="EDM", year=2014
    )
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path) as mock_tag,
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=claude_enriched),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "My Artist", "title": "My Title"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
                "user_edited_fields": ["artist", "title"],
            },
        )
    assert response.status_code == 200
    # Verify tag_file was called with merged metadata preserving user edits
    tagged_metadata = mock_tag.call_args[0][1]
    assert tagged_metadata.artist == "My Artist"  # user edited, preserved
    assert tagged_metadata.title == "My Title"  # user edited, preserved
    assert tagged_metadata.genre == "EDM"  # not edited, Claude fills in
    assert tagged_metadata.year == 2014  # not edited, Claude fills in
```

**Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 6: Run full verification**

Run: `uv run mypy server/ && uv run ruff check .`
Expected: PASS

**Step 7: Commit**

```bash
git add tests/test_app.py
git commit -m "test: update download tests for deferred enrichment, add enrichment+merge tests"
```

---

### Task 10: Final Verification

**Step 1: Run all Python checks**

Run: `uv run ruff check . && uv run mypy server/ && uv run pytest -v`
Expected: All PASS

**Step 2: Run all TypeScript checks**

Run: `cd extension && npx tsc --noEmit && npx eslint src/ && npm run build`
Expected: All PASS

**Step 3: Commit all remaining changes**

```bash
git add -A
git status  # verify no unexpected files
git commit -m "feat: defer Claude enrichment to parallel download with smart merge"
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
