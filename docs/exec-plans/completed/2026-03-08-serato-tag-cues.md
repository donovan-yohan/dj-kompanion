# Serato Tag Cues Implementation Plan

> **Status**: Completed | **Created**: 2026-03-08 | **Completed**: 2026-03-08
> **Design Doc**: `docs/design-docs/2026-03-08-serato-tag-cues-design.md`
> **For Claude:** Use /harness:orchestrate to execute this plan.

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-03-08 | Design | Write Serato GEOB tags instead of VDJ database.xml | VDJ reads Serato tags on scan; eliminates sync step |
| 2026-03-08 | Design | Switch default format to MP3 | Serato GEOB tags well-documented for MP3; M4A has known issues |
| 2026-03-08 | Design | Merge consecutive same-type sections | Prevents slot waste (e.g., "Verse 1, 2, 3" → single "Verse") |
| 2026-03-08 | Design | No hard cue limit | hotcues XT plugin provides page navigation; write every transition |
| 2026-03-08 | Design | Remove VDJ sync pipeline entirely | Writing to database.xml would override Serato tag cues |
| 2026-03-08 | Retrospective | Plan completed | 7 tasks, 3 surprises, 0 drift. Workers effective but need HTML validation. |

## Progress

- [x] Task 1: Section merging in analyzer _(completed 2026-03-08)_
- [x] Task 2: Serato tag writing module _(completed 2026-03-08)_
- [x] Task 3: Wire Serato tags into analysis pipeline _(completed 2026-03-08)_
- [x] Task 4: Remove VDJ sync pipeline (server) _(completed 2026-03-08)_
- [x] Task 5: Remove VDJ sync from extension _(completed 2026-03-08)_
- [x] Task 6: Change default format to MP3 _(completed 2026-03-08)_
- [x] Task 7: Update config and cleanup _(completed 2026-03-08)_

## Surprises & Discoveries

| Date | What | Impact | Resolution |
|------|------|--------|------------|
| 2026-03-08 | Task 2: serato-tools needed `# type: ignore[import-untyped]` inline, not just mypy override | Minor — same pattern as other untyped deps | Used existing pattern from `musicbrainzngs` |
| 2026-03-08 | Task 3: `write_serato_cues` was already imported by Task 2 worker and called at wrong location | Needed relocation into `if analysis_dir` block + error handling | Worker-3 moved and wrapped correctly |
| 2026-03-08 | Task 5: Worker removed closing `</script>` tag from popup.html along with sync footer | Download button permanently disabled — popup.js never executed | Fixed post-completion: restored `</script>` tag |

## Plan Drift

_None yet — updated when tasks deviate from plan during execution._

---

### Task 1: Section Merging in Analyzer

**Goal:** Add a merge step to `analyzer/edm_reclassify.py` that collapses consecutive same-type sections into one segment with summed bar counts. This runs before numbering.

**Files:**
- Modify: `analyzer/edm_reclassify.py`
- Create: `analyzer/tests/test_edm_reclassify.py` (or add to existing test if present)

**Step 1: Write the failing test**

Create `tests/test_edm_reclassify.py`:

```python
from analyzer.edm_reclassify import ClassifiedSegment, _merge_consecutive


def test_merge_consecutive_same_type():
    segments = [
        ClassifiedSegment(label="Verse", original_label="verse", start=0.0, end=15.0),
        ClassifiedSegment(label="Verse", original_label="verse", start=15.0, end=28.0),
        ClassifiedSegment(label="Verse", original_label="verse", start=28.0, end=45.0),
    ]
    merged = _merge_consecutive(segments)
    assert len(merged) == 1
    assert merged[0].label == "Verse"
    assert merged[0].start == 0.0
    assert merged[0].end == 45.0


def test_merge_preserves_different_types():
    segments = [
        ClassifiedSegment(label="Intro", original_label="intro", start=0.0, end=10.0),
        ClassifiedSegment(label="Verse", original_label="verse", start=10.0, end=25.0),
        ClassifiedSegment(label="Buildup", original_label="break", start=25.0, end=30.0),
    ]
    merged = _merge_consecutive(segments)
    assert len(merged) == 3
    assert [s.label for s in merged] == ["Intro", "Verse", "Buildup"]


def test_merge_non_consecutive_same_type_kept():
    """Two Drop sections separated by a Breakdown should remain separate."""
    segments = [
        ClassifiedSegment(label="Drop", original_label="chorus", start=0.0, end=30.0),
        ClassifiedSegment(label="Breakdown", original_label="break", start=30.0, end=45.0),
        ClassifiedSegment(label="Drop", original_label="chorus", start=45.0, end=75.0),
    ]
    merged = _merge_consecutive(segments)
    assert len(merged) == 3
    assert [s.label for s in merged] == ["Drop", "Breakdown", "Drop"]
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/donovanyohan/Documents/Programs/personal/yt-dlp-dj && uv run pytest tests/test_edm_reclassify.py -v`
Expected: FAIL — `_merge_consecutive` not found

**Step 3: Implement `_merge_consecutive` in `analyzer/edm_reclassify.py`**

Add before `_number_duplicates`:

```python
def _merge_consecutive(segments: list[ClassifiedSegment]) -> list[ClassifiedSegment]:
    """Merge consecutive segments with the same label into one.

    The merged segment spans from the first occurrence's start to the last
    occurrence's end. The original_label is taken from the first occurrence.
    """
    if not segments:
        return []

    merged: list[ClassifiedSegment] = [
        ClassifiedSegment(
            label=segments[0].label,
            original_label=segments[0].original_label,
            start=segments[0].start,
            end=segments[0].end,
        )
    ]
    for seg in segments[1:]:
        if seg.label == merged[-1].label:
            # Extend the current merged segment
            merged[-1] = ClassifiedSegment(
                label=merged[-1].label,
                original_label=merged[-1].original_label,
                start=merged[-1].start,
                end=seg.end,
            )
        else:
            merged.append(
                ClassifiedSegment(
                    label=seg.label,
                    original_label=seg.original_label,
                    start=seg.start,
                    end=seg.end,
                )
            )
    return merged
```

**Step 4: Update `reclassify_labels` to call merge before numbering**

In `reclassify_labels`, change:

```python
    _number_duplicates(classified)
    return classified
```

to:

```python
    merged = _merge_consecutive(classified)
    _number_duplicates(merged)
    return merged
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_edm_reclassify.py -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass (existing analyzer tests may need adjustment if they relied on unmerged output)

**Step 7: Commit**

```bash
git add analyzer/edm_reclassify.py tests/test_edm_reclassify.py
git commit -m "feat: merge consecutive same-type sections in analyzer"
```

---

### Task 2: Serato Tag Writing Module

**Goal:** Create `server/serato_tags.py` that writes Serato Markers2 GEOB frames into MP3 files using the `serato-tools` library.

**Files:**
- Modify: `pyproject.toml` (add `serato-tools` dependency)
- Modify: `pyproject.toml` (add mypy override for `serato_tools`)
- Create: `server/serato_tags.py`
- Create: `tests/test_serato_tags.py`

**Step 1: Add serato-tools dependency**

In `pyproject.toml`, add `"serato-tools"` to the `dependencies` list.

Add a mypy override:
```toml
[[tool.mypy.overrides]]
module = "serato_tools.*"
follow_imports = "skip"
```

Run: `uv sync` to install.

**Step 2: Research serato-tools API**

Before writing code, the worker must read the serato-tools source to understand:
- How to construct `TrackCuesV2` with a file path
- How to create new cue entries from scratch (not just modify existing)
- What fields the cue dataclass has (position units — milliseconds vs seconds)
- How `modify_entries` works vs direct cue list assignment

Check: `uv run python -c "from serato_tools.track_cues_v2 import TrackCuesV2; help(TrackCuesV2)"` or explore the installed package source.

**Step 3: Write the failing test**

Create `tests/test_serato_tags.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

from server.models import AnalysisResult, SegmentInfo
from server.serato_tags import write_serato_cues


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        bpm=128.0,
        key="Bb",
        key_camelot="6A",
        beats=[],
        downbeats=[],
        segments=[
            SegmentInfo(label="Intro", original_label="intro", start=0.0, end=15.0, bars=8),
            SegmentInfo(label="Drop", original_label="chorus", start=15.0, end=45.0, bars=16),
            SegmentInfo(label="Outro", original_label="outro", start=45.0, end=60.0, bars=8),
        ],
    )


def test_write_serato_cues_skips_non_mp3(tmp_path: Path):
    """Should return False for non-MP3 files."""
    m4a_file = tmp_path / "test.m4a"
    m4a_file.write_bytes(b"fake")
    result = write_serato_cues(m4a_file, _sample_result())
    assert result is False


def test_write_serato_cues_writes_to_mp3(tmp_path: Path):
    """Should write GEOB frames to an MP3 file and return True."""
    # Create a real minimal MP3 file for mutagen to accept
    # The actual serato-tools interaction will be mocked
    mp3_file = tmp_path / "test.mp3"
    mp3_file.write_bytes(b"fake mp3")  # Will need a real MP3 or mock

    # This test should verify write_serato_cues calls serato-tools correctly
    # Implementation depends on discovered API — worker should adapt
    result = write_serato_cues(mp3_file, _sample_result())
    assert result is True
```

Note: The worker must adapt these tests based on the actual serato-tools API discovered in Step 2. The key behaviors to test:
- Returns False for non-MP3 files
- Returns True after successfully writing cues to MP3
- Each segment becomes a cue with correct name format (`"Intro (8 bars)"`)
- Gracefully returns False on serato-tools errors

**Step 4: Implement `server/serato_tags.py`**

```python
"""Write Serato Markers2 GEOB tags for VDJ cue point import."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from server.models import AnalysisResult

logger = logging.getLogger(__name__)


def _build_cue_name(label: str, bars: int) -> str:
    """Build cue name like 'Drop (16 bars)'."""
    bar_word = "bar" if bars == 1 else "bars"
    return f"{label} ({bars} {bar_word})"


def write_serato_cues(filepath: Path, result: AnalysisResult) -> bool:
    """Write analysis segments as Serato hot cues into an MP3 file.

    Returns True if cues were written, False if skipped or failed.
    Only works with MP3 files — returns False for other formats.
    """
    if filepath.suffix.lower() != ".mp3":
        logger.debug("Skipping Serato tag write for non-MP3 file: %s", filepath)
        return False

    try:
        # Import here to keep serato-tools optional at module level
        from serato_tools.track_cues_v2 import TrackCuesV2
        # Worker: adapt this implementation based on actual serato-tools API
        # discovered in Step 2. The general pattern is:
        # 1. Open file with TrackCuesV2(filepath)
        # 2. Create cue entries for each segment
        # 3. Save
        tags = TrackCuesV2(str(filepath))

        # Build cue list from segments
        # Worker must discover: how to create cue objects, position format, etc.
        for i, seg in enumerate(result.segments):
            name = _build_cue_name(seg.label, seg.bars)
            # tags.set_cue(index=i, position=seg.start, name=name, ...)
            # ^ Exact API TBD — worker must check serato-tools source

        tags.save()
        logger.info("Wrote %d Serato cues to %s", len(result.segments), filepath)
        return True
    except Exception:
        logger.warning("Failed to write Serato tags to %s", filepath, exc_info=True)
        return False
```

The worker MUST research the actual serato-tools API and fill in the cue creation logic. The skeleton above shows the structure.

**Step 5: Run tests**

Run: `uv run pytest tests/test_serato_tags.py -v`
Expected: PASS

**Step 6: Run type check**

Run: `uv run mypy server/serato_tags.py`
Expected: PASS (with mypy override for serato_tools)

**Step 7: Commit**

```bash
git add pyproject.toml server/serato_tags.py tests/test_serato_tags.py
git commit -m "feat: add Serato GEOB tag writer for MP3 cue points"
```

---

### Task 3: Wire Serato Tags into Analysis Pipeline

**Goal:** Call `write_serato_cues` from `server/analyzer.py` after writing `.meta.json`, before marking track as "analyzed".

**Files:**
- Modify: `server/analyzer.py`
- Modify: `tests/test_analyzer.py`

**Step 1: Write the failing test**

In `tests/test_analyzer.py`, add a test that verifies `write_serato_cues` is called after analysis:

```python
@pytest.mark.asyncio
async def test_analyze_audio_calls_serato_writer(tmp_path, mock_httpx_success):
    """After successful analysis, write_serato_cues should be called."""
    filepath = tmp_path / "test.mp3"
    filepath.write_bytes(b"fake")
    db_path = tmp_path / "tracks.db"
    init_db(db_path)
    upsert_track(db_path, str(filepath))

    with patch("server.analyzer.write_serato_cues") as mock_serato:
        mock_serato.return_value = True
        await analyze_audio(
            filepath,
            db_path=db_path,
            analysis_dir=tmp_path / "analysis",
            output_dir=tmp_path,
        )
        mock_serato.assert_called_once()
        call_args = mock_serato.call_args
        assert call_args[0][0] == filepath  # filepath arg
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyzer.py::test_analyze_audio_calls_serato_writer -v`
Expected: FAIL — `write_serato_cues` not imported

**Step 3: Wire into analyzer.py**

In `server/analyzer.py`, add import:

```python
from server.serato_tags import write_serato_cues
```

After the `.meta.json` save block (around line 92), add:

```python
    # Write Serato GEOB tags for VDJ auto-import (best-effort)
    try:
        write_serato_cues(filepath, result)
    except Exception:
        logger.warning("Serato tag write failed for %s", filepath, exc_info=True)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_analyzer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/analyzer.py tests/test_analyzer.py
git commit -m "feat: write Serato cue tags after analysis completes"
```

---

### Task 4: Remove VDJ Sync Pipeline (Server)

**Goal:** Delete VDJ database.xml writing code, sync endpoint, and related models/config/db functions.

**Files:**
- Delete: `server/vdj.py`
- Delete: `server/vdj_sync.py`
- Delete: `tests/test_vdj.py`
- Delete: `tests/test_vdj_sync.py`
- Modify: `server/app.py` — remove sync-vdj endpoint and imports
- Modify: `server/models.py` — remove `SyncVdjResponse`, `synced_at` from `TrackStatus`
- Modify: `server/track_db.py` — remove `mark_synced`, `get_unsynced`, `synced_at` column
- Modify: `server/config.py` — remove `vdj_database`, `max_cues` from `AnalysisConfig`
- Modify: `tests/test_app.py` — remove sync-vdj test(s)
- Modify: `tests/test_analyzer.py` — remove any `vdj` references if present

**Step 1: Delete VDJ files**

```bash
rm server/vdj.py server/vdj_sync.py tests/test_vdj.py tests/test_vdj_sync.py
```

**Step 2: Remove from `server/app.py`**

Remove these imports:
```python
from server.vdj_sync import sync_vdj
```

Remove from the models import:
```python
SyncVdjResponse,
```

Remove the entire `sync_vdj_endpoint` function (the `@app.post("/api/sync-vdj", ...)` block).

**Step 3: Remove from `server/models.py`**

Delete the `SyncVdjResponse` class entirely.

Remove `synced_at: str | None = None` from `TrackStatus`.

**Step 4: Remove from `server/track_db.py`**

Delete `mark_synced` function.
Delete `get_unsynced` function.

Remove `synced_at` from `TrackRow` dataclass, `_row_to_track`, the `_CREATE_TABLE` SQL, and the `upsert_track` INSERT/UPDATE.

**Step 5: Remove from `server/config.py`**

In `AnalysisConfig`, remove:
```python
vdj_database: Path = _default_vdj_database()
max_cues: int = 8
```

Delete the `_default_vdj_database()` function.

In `_serializable_defaults()`, remove `"vdj_database"` and `"max_cues"` from the analysis dict.

**Step 6: Update `tests/test_app.py`**

Remove any test functions related to `sync_vdj`, `SyncVdjResponse`.

**Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass (some tests may need import fixes)

**Step 8: Run type check and lint**

Run: `uv run mypy server/ && uv run ruff check .`
Expected: PASS

**Step 9: Commit**

```bash
git add -A
git commit -m "refactor: remove VDJ database.xml sync pipeline"
```

---

### Task 5: Remove VDJ Sync from Extension

**Goal:** Remove the sync button, sync API call, and sync types from the Chrome extension.

**Files:**
- Modify: `extension/popup.html` — remove sync footer
- Modify: `extension/popup.css` — remove sync footer styles
- Modify: `extension/src/popup.ts` — remove `handleSyncVdj`, sync button wiring, sync import
- Modify: `extension/src/api.ts` — remove `requestSyncVdj` function and `SyncVdjResponse` import
- Modify: `extension/src/types.ts` — remove `SyncVdjResponse` interface, `synced_at` from `TrackStatus`

**Step 1: Remove sync footer from `extension/popup.html`**

Delete:
```html
    <!-- Sync footer -->
    <footer id="section-sync">
      <button id="btn-sync-vdj" class="btn btn-secondary" disabled>Sync to VDJ</button>
      <span id="sync-status" class="sync-status"></span>
    </footer>
```

**Step 2: Remove sync styles from `extension/popup.css`**

Delete the `/* Sync footer */` section (lines 339-357):
```css
/* Sync footer */
footer { ... }
footer .btn { ... }
.sync-status { ... }
```

**Step 3: Remove from `extension/src/popup.ts`**

Remove `requestSyncVdj` from the import line.
Delete the `handleSyncVdj` async function.
Remove the sync button wiring in `init()` (the `syncBtn` lines).
Remove the `btn-sync-vdj` click listener in `DOMContentLoaded`.

**Step 4: Remove from `extension/src/api.ts`**

Remove the `SyncVdjResponse` import from the types import line.
Delete the `requestSyncVdj` function.

**Step 5: Remove from `extension/src/types.ts`**

Delete the `SyncVdjResponse` interface.
Remove `synced_at: string | null;` from `TrackStatus`.

**Step 6: Build and type-check extension**

Run: `cd extension && npm run build && npx tsc --noEmit`
Expected: PASS

**Step 7: Lint extension**

Run: `cd extension && npm run lint`
Expected: PASS

**Step 8: Commit**

```bash
git add extension/
git commit -m "refactor: remove VDJ sync button and API from extension"
```

---

### Task 6: Change Default Format to MP3

**Goal:** Change the extension's default download format from M4A to MP3.

**Files:**
- Modify: `extension/popup.html` — reorder `<option>` tags (MP3 first)
- Modify: `extension/src/popup.ts` — change default format fallback

**Step 1: Update `extension/popup.html`**

Change the format select to put MP3 first (as `selected`):
```html
<select id="format-select" class="format-select">
  <option value="mp3">MP3</option>
  <option value="m4a">M4A</option>
  <option value="flac">FLAC</option>
  <option value="ogg">OGG</option>
</select>
```

**Step 2: Update `extension/src/popup.ts`**

In `getSelectedFormat()`, change the fallback:
```typescript
return (document.getElementById("format-select") as HTMLSelectElement)?.value ?? "mp3";
```

In `init()`, change the storage default:
```typescript
const stored = await chrome.storage.sync.get({ format: "mp3" });
```

**Step 3: Build extension**

Run: `cd extension && npm run build`
Expected: PASS

**Step 4: Commit**

```bash
git add extension/
git commit -m "feat: change default download format to MP3"
```

---

### Task 7: Update Config and Cleanup

**Goal:** Final cleanup — ensure config serialization works without removed fields, run full validation.

**Files:**
- Verify: `server/config.py` changes from Task 4 are clean
- Modify: `tests/test_app.py` if any remaining references to removed code
- Modify: `docs/ARCHITECTURE.md` — update module list and data flow

**Step 1: Run full Python test suite**

Run: `uv run pytest -v`
Expected: All pass

**Step 2: Run full type check**

Run: `uv run mypy server/`
Expected: PASS

**Step 3: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: PASS

**Step 4: Build extension**

Run: `cd extension && npm run build && npx tsc --noEmit && npm run lint`
Expected: PASS

**Step 5: Update `docs/ARCHITECTURE.md`**

In the Code Map table:
- Remove `server/vdj.py` row
- Remove `server/vdj_sync.py` row
- Add `server/serato_tags.py` row: "Serato Markers2 GEOB writer for MP3 hot cue import into VDJ"

Update Data Flow section:
- Remove step 5 (VDJ Sync)
- Modify step 4 (Analysis) to mention Serato tag writing after .meta.json

Update Cross-Cutting Concerns:
- Replace "VDJ cue priority" row with "Serato cue tags" description
- Remove "VDJ safety" row
- Update "Analysis storage" to mention Serato GEOB tags

**Step 6: Commit**

```bash
git add docs/ tests/
git commit -m "docs: update architecture for Serato tag cues pipeline"
```

---

## Outcomes & Retrospective

All 7 tasks completed. Serato GEOB cue tags now written directly into MP3 files after analysis. VDJ sync pipeline fully removed. Default format switched to MP3.

**What worked:**
- Parallel worker dispatch completed 7 tasks efficiently
- Section merging logic (merge-before-number) works cleanly
- serato-tools library integration was straightforward
- Complete VDJ sync removal was the right call — cleaner than deprecation

**What didn't:**
- Task 5 worker dropped the `</script>` closing tag from popup.html, breaking the extension completely — caught only when user tested
- Task 2 and Task 3 workers had overlapping scope (both tried to wire serato_tags into analyzer.py)
- No integration testing caught the HTML breakage since extension tests aren't automated

**Learnings to codify:**
- Workers modifying HTML should be validated with a build + basic structural check
- Parallel workers on adjacent tasks can create merge conflicts — sequential dispatch is safer for tightly coupled changes
- serato-tools v4.0.1 uses `modify_entries(callback)` pattern with `CueEntry` dataclass (position in ms, 3-byte RGB color)
