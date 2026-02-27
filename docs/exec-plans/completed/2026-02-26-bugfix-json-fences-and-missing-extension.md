# Bugfix: JSON Fence Stripping & Missing File Extension

> **Status**: Completed | **Created**: 2026-02-26 | **Completed**: 2026-02-27
> **Design Doc**: Bug report (no design doc — two production bugs)
> **For Claude:** Use /harness:orchestrate to execute this plan.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two bugs causing download failures: (1) Claude CLI returns JSON wrapped in markdown code fences that our parser doesn't strip, and (2) yt-dlp downloads produce files without extensions when `preferred_format == "best"`, crashing the tagger.

**Architecture:** Both fixes are in the Python server. Bug 1 adds a fence-stripping step to `_parse_claude_response` in `server/enrichment.py`. Bug 2 adds `%(ext)s` to the yt-dlp `outtmpl` in `server/downloader.py` so the downloaded file and returned path always have the correct extension.

**Tech Stack:** Python, FastAPI, yt-dlp, mutagen, pytest

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-02-26 | Bug 1 | Strip markdown fences with regex before JSON parsing | Claude CLI sometimes wraps JSON in `` ```json ... ``` `` despite `--output-format json`; robust parsing handles this gracefully |
| 2026-02-26 | Bug 2 | Add `%(ext)s` to outtmpl rather than post-hoc file discovery | Lets yt-dlp set the correct extension natively; `prepare_filename` then returns the right path; existing `with_suffix` logic for `preferred_format != "best"` still works |
| 2026-02-27 | Retrospective | Plan completed | Both bugs fixed with minimal changes (13 lines in enrichment.py, 1 line in downloader.py) + 6 new tests |

## Progress

- [x] Task 1: Strip markdown code fences from Claude responses _(completed 2026-02-27)_
- [x] Task 2: Fix missing file extension in downloads _(completed 2026-02-27)_
- [x] Task 3: Final verification _(completed 2026-02-27)_

## Surprises & Discoveries

| Date | What | Impact | Action |
|------|------|--------|--------|
| 2026-02-27 | `tests/test_downloader.py` already existed with 17 tests | Plan assumed file might not exist | Worker added tests to existing class structure instead |

## Plan Drift

| Task | Plan Said | Actually Did | Why |
|------|-----------|-------------|-----|
| Task 2 | Create `tests/test_downloader.py` as standalone functions | Added 3 tests as methods in existing `TestDownloadAudio` class | File already existed with class-based test organization; consistency |

---

### Task 1: Strip Markdown Code Fences from Claude Responses

**Files:**
- Modify: `server/enrichment.py`
- Modify: `tests/test_enrichment.py`

**Context:** Claude CLI sometimes returns JSON wrapped in markdown code fences like:
```
\`\`\`json
{"artist": "Ninajirachi", ...}
\`\`\`
```
The `_parse_claude_response` function at `server/enrichment.py:115` tries `json.loads` directly, which fails on the fenced text.

**Step 1: Write failing tests**

Add to `tests/test_enrichment.py` after the existing `test_enrich_metadata_handles_json_envelope` test:

```python
def test_enrich_metadata_handles_markdown_fenced_json() -> None:
    """Test that markdown code fences are stripped before parsing."""
    raw = make_raw()
    inner = claude_json(artist="Ninajirachi", title="iPod Touch", genre="Indie Pop")
    fenced = f"```json\n{inner}\n```"

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(fenced)):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "Ninajirachi"
    assert result.title == "iPod Touch"
    assert result.genre == "Indie Pop"


def test_enrich_metadata_handles_markdown_fenced_no_lang() -> None:
    """Test that markdown fences without language tag are also stripped."""
    raw = make_raw()
    inner = claude_json(artist="Bicep", title="GLUE")
    fenced = f"```\n{inner}\n```"

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(fenced)):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "Bicep"
    assert result.title == "GLUE"


def test_try_enrich_handles_markdown_fenced_json() -> None:
    """Test that try_enrich also handles fenced JSON."""
    raw = make_raw()
    inner = claude_json(artist="Fred again..", title="Delilah")
    fenced = f"```json\n{inner}\n```"

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(fenced)):
        result = asyncio.run(try_enrich_metadata(raw))

    assert result is not None
    assert result.artist == "Fred again.."
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_enrichment.py -k "markdown_fenced" -v`
Expected: FAIL — 3 failures (JSON parsing fails on fenced text, falls back to basic_enrich / returns None)

**Step 3: Implement fence stripping**

In `server/enrichment.py`, add the regex constant after the existing `_SUFFIXES` list (around line 27):

```python
_MARKDOWN_FENCE_RE = re.compile(r"^```\w*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
```

Then add a helper function after the constant:

```python
def _strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from text if present."""
    match = _MARKDOWN_FENCE_RE.match(text.strip())
    if match:
        return match.group(1)
    return text
```

Then modify `_parse_claude_response` to call it. Insert one line after the envelope try/except block (after line 126, before line 128):

```python
    text_to_parse = _strip_markdown_fences(text_to_parse)
```

The full function should look like:

```python
def _parse_claude_response(response_text: str, raw: RawMetadata) -> EnrichedMetadata | None:
    """Parse JSON response from claude CLI. Returns None if parsing fails."""
    text_to_parse = response_text

    try:
        envelope: Any = json.loads(response_text)
        if isinstance(envelope, dict) and "result" in envelope:
            result_val = envelope["result"]
            if isinstance(result_val, str):
                text_to_parse = result_val
    except json.JSONDecodeError:
        pass

    text_to_parse = _strip_markdown_fences(text_to_parse)

    try:
        raw_parsed: Any = json.loads(text_to_parse)
    except json.JSONDecodeError:
        logger.warning("claude returned invalid JSON (first 200 chars): %.200s", text_to_parse)
        return None

    # ... rest unchanged
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_enrichment.py -k "markdown_fenced" -v`
Expected: PASS — all 3 tests green

**Step 5: Run full enrichment test suite**

Run: `uv run pytest tests/test_enrichment.py -v`
Expected: PASS — all existing tests still pass

**Step 6: Run mypy and ruff**

Run: `uv run mypy server/enrichment.py && uv run ruff check server/enrichment.py`
Expected: PASS

**Step 7: Commit**

```bash
git add server/enrichment.py tests/test_enrichment.py
git commit -m "fix(enrichment): strip markdown code fences from Claude JSON responses"
```

---

### Task 2: Fix Missing File Extension in Downloads

**Files:**
- Modify: `server/downloader.py`
- Modify: `tests/test_downloader.py` (create if not exists)

**Context:** `_download_audio_sync` in `server/downloader.py:70` sets `outtmpl` to `str(output_dir / filename)` where `filename` has no extension (e.g., `"Ninajirachi - iPod Touch"`). When `preferred_format == "best"`, no postprocessor runs and the code returns `Path(ydl.prepare_filename(info))` which has no extension. But yt-dlp actually saves the file with an extension. The tagger then fails with "Unsupported format: ." because `Path.suffix` is empty.

**Fix:** Append `.%(ext)s` to the `outtmpl` so yt-dlp includes the extension in both the filename on disk and the value returned by `prepare_filename`.

**Step 1: Check if test file exists**

Run: `ls tests/test_downloader.py 2>/dev/null || echo "not found"`

**Step 2: Write failing test**

If `tests/test_downloader.py` doesn't exist, create it. Add:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.downloader import _download_audio_sync


def _make_info(ext: str = "webm") -> dict[str, Any]:
    """Minimal yt-dlp info dict."""
    return {
        "id": "test123",
        "title": "Test",
        "ext": ext,
    }


def test_download_best_format_has_extension(tmp_path: Path) -> None:
    """When preferred_format is 'best', returned path must have file extension."""
    info = _make_info(ext="webm")
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = info
    mock_ydl.prepare_filename.return_value = str(tmp_path / "Artist - Title.webm")
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    with patch("server.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = _download_audio_sync(
            url="https://example.com",
            output_dir=tmp_path,
            filename="Artist - Title",
            preferred_format="best",
        )

    assert result.suffix != "", f"Expected file extension, got: {result}"
    assert result.suffix == ".webm"


def test_download_preferred_format_overrides_extension(tmp_path: Path) -> None:
    """When preferred_format is set, extension should match it."""
    info = _make_info(ext="webm")
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = info
    mock_ydl.prepare_filename.return_value = str(tmp_path / "Artist - Title.webm")
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    with patch("server.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
        result = _download_audio_sync(
            url="https://example.com",
            output_dir=tmp_path,
            filename="Artist - Title",
            preferred_format="mp3",
        )

    assert result.suffix == ".mp3"


def test_download_outtmpl_includes_ext_placeholder(tmp_path: Path) -> None:
    """Verify outtmpl includes %(ext)s so yt-dlp adds the extension."""
    info = _make_info(ext="m4a")
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = info
    mock_ydl.prepare_filename.return_value = str(tmp_path / "Artist - Title.m4a")
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)

    captured_opts: list[dict[str, Any]] = []
    original_init = MagicMock(return_value=mock_ydl)

    def capture_init(*args: Any, **kwargs: Any) -> MagicMock:
        if args:
            captured_opts.append(args[0])
        return mock_ydl

    with patch("server.downloader.yt_dlp.YoutubeDL", side_effect=capture_init):
        _download_audio_sync(
            url="https://example.com",
            output_dir=tmp_path,
            filename="Artist - Title",
            preferred_format="best",
        )

    assert captured_opts, "YoutubeDL was not called"
    outtmpl = captured_opts[0]["outtmpl"]
    assert "%(ext)s" in outtmpl, f"outtmpl missing %(ext)s: {outtmpl}"
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_downloader.py -v`
Expected: FAIL — `test_download_best_format_has_extension` and `test_download_outtmpl_includes_ext_placeholder` fail (path has no extension, outtmpl lacks `%(ext)s`)

**Step 4: Fix the outtmpl**

In `server/downloader.py`, line 89, change:

```python
        "outtmpl": str(output_dir / filename),
```

to:

```python
        "outtmpl": str(output_dir / filename) + ".%(ext)s",
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_downloader.py -v`
Expected: PASS — all 3 tests green

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS — all tests pass (no existing tests break because mock `prepare_filename` return values already include extensions)

**Step 7: Run mypy and ruff**

Run: `uv run mypy server/downloader.py && uv run ruff check server/downloader.py tests/test_downloader.py`
Expected: PASS

**Step 8: Commit**

```bash
git add server/downloader.py tests/test_downloader.py
git commit -m "fix(downloader): add %(ext)s to outtmpl so downloads always have file extension"
```

---

### Task 3: Final Verification

**Step 1: Run all Python checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy server/ && uv run pytest -v`
Expected: All PASS

**Step 2: Run TypeScript checks** (extension unchanged, sanity check)

Run: `cd extension && npx tsc --noEmit`
Expected: PASS

**Step 3: Format if needed**

Run: `uv run ruff format .`

**Step 4: Final commit if formatting changes**

```bash
git add -A
git status  # verify no unexpected files
git commit -m "style: apply ruff formatting"
```

---

## Outcomes & Retrospective

**What worked:**
- Parallel worker dispatch for independent tasks — both bugs fixed simultaneously
- Plan was accurate; minimal drift (only Task 2 test structure differed)
- TDD approach caught the bugs cleanly

**What didn't:**
- Plan assumed `tests/test_downloader.py` might not exist (it did, with 17 tests) — should have checked during planning

**Learnings to codify:**
- Claude CLI `--output-format json` does not guarantee unwrapped JSON — always strip markdown fences defensively
- yt-dlp `outtmpl` must include `%(ext)s` or the output path will have no extension when no postprocessor runs
