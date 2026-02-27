# Audio Post-Processing Implementation Plan

> **Status**: Active | **Created**: 2026-02-27 | **Last Updated**: 2026-02-27
> **Design Doc**: `docs/design-docs/2026-02-27-audio-post-processing-design.md`
> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ML-based audio analysis to the post-download pipeline — detecting song structure (with EDM reclassification), BPM, key, bar counts — and writing results as named cue points to Virtual DJ's database.xml.

**Architecture:** New `server/analyzer.py` module with a 5-stage pipeline: allin1 for structure/beats, essentia for key detection, custom EDM reclassifier using Demucs stem energy, bar counting via downbeats, and beat-snapping. A new `server/vdj.py` module handles database.xml read-modify-write. Post-download trigger fires analysis as a background task. New `/api/analyze` endpoint for on-demand re-analysis.

**Tech Stack:** allin1 (structure + beats + BPM), essentia (key detection, bgate EDM profile), PyTorch/Demucs (via allin1), mutagen (existing), xml.etree.ElementTree (VDJ database), numpy (energy computation).

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-02-27 | Design | allin1 + essentia + custom EDM reclassifier | Best accuracy-to-effort ratio; allin1 is SOTA for structure, essentia has EDM-tuned key profiles |
| 2026-02-27 | Design | Post-download hook trigger | Non-blocking; download succeeds independently of analysis |
| 2026-02-27 | Design | VDJ database.xml for cue points | VDJ stores cues in XML sidecar, not in file tags |
| 2026-02-27 | Design | Named hot cues with bar counts | "Drop 1 (16 bars)" format visible on waveform |
| 2026-02-27 | Design | Priority-based cue slot filling (max 8) | Drop > Buildup > Breakdown > Intro > Outro > Verse > Bridge > Inst/Solo |
| 2026-02-27 | Design | keep_byproducts=True for Demucs stems | allin1 doesn't expose stems in AnalysisResult; must save to disk via demix_dir |
| 2026-02-27 | Design | Separate Demucs stem energy computation | Load saved stems with librosa/numpy after allin1 completes |

## Progress

- [x] Task 1: Add ML dependencies to project _(completed 2026-02-27)_
- [x] Task 2: Add analysis models to server/models.py _(completed 2026-02-27)_
- [x] Task 3: Build key detection module (server/key_detect.py) _(completed 2026-02-27)_
- [x] Task 4: Build beat-snapping and bar-counting utilities (server/beat_utils.py) _(completed 2026-02-27)_
- [x] Task 5: Build EDM reclassifier (server/edm_reclassify.py) _(completed 2026-02-27)_
- [x] Task 6: Build VDJ database writer (server/vdj.py) _(completed 2026-02-27)_
- [x] Task 7: Build analyzer orchestrator (server/analyzer.py) _(completed 2026-02-27)_
- [x] Task 8: Add /api/analyze endpoint and post-download trigger _(completed 2026-02-27)_
- [x] Task 9: Update extension types, API, and queue status display _(completed 2026-02-27)_
- [x] Task 10: Integration test — end-to-end verify _(completed 2026-02-27)_

## Surprises & Discoveries

| Date | What was unexpected | How it affects the plan | What was done |
|------|---------------------|------------------------|---------------|
| 2026-02-27 | allin1/NATTEN incompatible on macOS ARM64 — NATTEN has no macOS wheels (CUDA only), and API completely rewritten in 0.20+ | allin1 cannot be imported natively; analyzer.py uses try/except fallback | Code written with direct import + fallback; Docker container approach chosen for production use (future task) |
| 2026-02-27 | madmom 0.16.1 broken on Python 3.13+ (collections.MutableSequence removed) | Must install from git HEAD | Added `madmom = {git = "https://github.com/CPJKU/madmom.git"}` to uv sources |

## Plan Drift

| Task | What the plan said | What actually happened | Why |
|------|--------------------|------------------------|-----|
| Task 1 | Install allin1 and verify it imports | allin1 installed but cannot import due to NATTEN | NATTEN has no macOS ARM64 support; Docker approach deferred |
| Task 7 | Direct `allin1.analyze()` call | Uses `try: import allin1` with graceful None fallback | Allows server to start without allin1; Docker integration deferred |

---

## Task 1: Add ML dependencies to project

**Goal:** Install allin1, essentia, and numpy into the uv environment. Verify they import on macOS.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies to pyproject.toml**

Add to `[project] dependencies`:

```toml
dependencies = [
    "fastapi",
    "uvicorn",
    "yt-dlp[default]",
    "mutagen",
    "typer",
    "pyyaml",
    "pydantic",
    "allin1",
    "essentia",
    "numpy",
]
```

**Step 2: Install dependencies**

Run: `uv sync`

Expected: Dependencies resolve and install. PyTorch, Demucs, NATTEN, madmom pulled in as allin1 transitive deps. essentia installs from pre-built macOS ARM64 wheel.

**Step 3: Verify imports**

Run: `uv run python -c "import allin1; import essentia.standard; import numpy; print('OK')"`

Expected: `OK` — no import errors.

If NATTEN fails on macOS, try: `uv run pip install natten` separately or check NATTEN GitHub for macOS-specific install instructions.

**Step 4: Add mypy overrides for untyped ML libs**

In `pyproject.toml`, add overrides so mypy doesn't choke on untyped ML packages:

```toml
[[tool.mypy.overrides]]
module = "allin1.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "essentia.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "demucs.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "madmom.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "natten.*"
ignore_missing_imports = true
```

**Step 5: Verify mypy still passes**

Run: `uv run mypy server/`

Expected: No new errors.

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add allin1, essentia, numpy for audio analysis"
```

---

## Task 2: Add analysis models to server/models.py

**Goal:** Add `SegmentInfo`, `AnalysisResult`, `AnalyzeRequest`, and `AnalyzeResponse` Pydantic models.

**Files:**
- Modify: `server/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
"""Tests for analysis-related models in server/models.py."""

from __future__ import annotations

from server.models import AnalysisResult, AnalyzeRequest, SegmentInfo


class TestSegmentInfo:
    def test_create_segment(self) -> None:
        seg = SegmentInfo(
            label="Drop",
            original_label="chorus",
            start=75.3,
            end=105.7,
            bars=16,
        )
        assert seg.label == "Drop"
        assert seg.original_label == "chorus"
        assert seg.start == 75.3
        assert seg.end == 105.7
        assert seg.bars == 16


class TestAnalysisResult:
    def test_create_result(self) -> None:
        result = AnalysisResult(
            bpm=128.0,
            key="Am",
            key_camelot="8A",
            beats=[0.234, 0.703, 1.172],
            downbeats=[0.234, 1.172],
            segments=[
                SegmentInfo(
                    label="Intro",
                    original_label="intro",
                    start=0.234,
                    end=60.5,
                    bars=32,
                ),
            ],
            vdj_written=False,
        )
        assert result.bpm == 128.0
        assert result.key == "Am"
        assert result.key_camelot == "8A"
        assert len(result.beats) == 3
        assert len(result.segments) == 1
        assert result.segments[0].label == "Intro"
        assert result.vdj_written is False

    def test_vdj_written_defaults_false(self) -> None:
        result = AnalysisResult(
            bpm=128.0,
            key="Am",
            key_camelot="8A",
            beats=[],
            downbeats=[],
            segments=[],
        )
        assert result.vdj_written is False


class TestAnalyzeRequest:
    def test_create_request(self) -> None:
        req = AnalyzeRequest(filepath="/path/to/track.m4a")
        assert req.filepath == "/path/to/track.m4a"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`

Expected: FAIL with ImportError (SegmentInfo, AnalysisResult, AnalyzeRequest not defined yet).

**Step 3: Write the models**

In `server/models.py`, add after `HealthResponse`:

```python
class SegmentInfo(BaseModel):
    label: str
    original_label: str
    start: float
    end: float
    bars: int


class AnalysisResult(BaseModel):
    bpm: float
    key: str
    key_camelot: str
    beats: list[float]
    downbeats: list[float]
    segments: list[SegmentInfo]
    vdj_written: bool = False


class AnalyzeRequest(BaseModel):
    filepath: str


class AnalyzeResponse(BaseModel):
    status: str
    analysis: AnalysisResult
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`

Expected: All PASS.

**Step 5: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 6: Commit**

```bash
git add server/models.py tests/test_models.py
git commit -m "feat(models): add SegmentInfo, AnalysisResult, AnalyzeRequest models"
```

---

## Task 3: Build key detection module (server/key_detect.py)

**Goal:** Wrap essentia's KeyExtractor with Camelot notation conversion. Pure function, no side effects.

**Files:**
- Create: `server/key_detect.py`
- Create: `tests/test_key_detect.py`

**Step 1: Write the failing test**

Create `tests/test_key_detect.py`:

```python
"""Tests for server/key_detect.py — musical key detection + Camelot conversion."""

from __future__ import annotations

import pytest

from server.key_detect import to_camelot, to_standard_notation


class TestToStandardNotation:
    def test_major(self) -> None:
        assert to_standard_notation("C", "major") == "C"

    def test_minor(self) -> None:
        assert to_standard_notation("A", "minor") == "Am"

    def test_sharp(self) -> None:
        assert to_standard_notation("F#", "minor") == "F#m"


class TestToCamelot:
    def test_a_minor(self) -> None:
        assert to_camelot("A", "minor") == "8A"

    def test_c_major(self) -> None:
        assert to_camelot("C", "major") == "8B"

    def test_f_sharp_minor(self) -> None:
        assert to_camelot("F#", "minor") == "11A"

    def test_b_flat_major(self) -> None:
        assert to_camelot("Bb", "major") == "6B"

    def test_unknown_key_returns_empty(self) -> None:
        assert to_camelot("X", "major") == ""

    @pytest.mark.parametrize(
        ("key", "scale", "expected"),
        [
            ("B", "major", "1B"),
            ("Ab", "minor", "1A"),
            ("E", "major", "12B"),
            ("Db", "minor", "12A"),
        ],
    )
    def test_camelot_endpoints(self, key: str, scale: str, expected: str) -> None:
        assert to_camelot(key, scale) == expected
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_key_detect.py -v`

Expected: FAIL with ImportError.

**Step 3: Write the implementation**

Create `server/key_detect.py`:

```python
"""Musical key detection and Camelot notation conversion."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CAMELOT_MAJOR: dict[str, str] = {
    "B": "1B", "F#": "2B", "Db": "3B", "Ab": "4B",
    "Eb": "5B", "Bb": "6B", "F": "7B", "C": "8B",
    "G": "9B", "D": "10B", "A": "11B", "E": "12B",
}

_CAMELOT_MINOR: dict[str, str] = {
    "Ab": "1A", "Eb": "2A", "Bb": "3A", "F": "4A",
    "C": "5A", "G": "6A", "D": "7A", "A": "8A",
    "E": "9A", "B": "10A", "F#": "11A", "Db": "12A",
}


def to_standard_notation(key: str, scale: str) -> str:
    """Convert key + scale to standard DJ notation (e.g., 'Am', 'F#m', 'C')."""
    if scale == "minor":
        return f"{key}m"
    return key


def to_camelot(key: str, scale: str) -> str:
    """Convert key + scale to Camelot wheel notation (e.g., '8A', '11B')."""
    table = _CAMELOT_MINOR if scale == "minor" else _CAMELOT_MAJOR
    return table.get(key, "")


def _detect_key_sync(filepath: Path) -> tuple[str, str, float]:
    """Run essentia KeyExtractor. Returns (key, scale, strength)."""
    import essentia.standard as es  # type: ignore[import-untyped]

    audio: Any = es.MonoLoader(filename=str(filepath))()
    key_extractor: Any = es.KeyExtractor(profileType="bgate")
    key: str
    scale: str
    strength: float
    key, scale, strength = key_extractor(audio)
    return key, scale, float(strength)


async def detect_key(filepath: Path) -> tuple[str, str, str, float]:
    """Detect musical key of an audio file.

    Returns (standard_notation, camelot_notation, scale, strength).
    Example: ("Am", "8A", "minor", 0.87)
    """
    key, scale, strength = await asyncio.to_thread(_detect_key_sync, filepath)
    standard = to_standard_notation(key, scale)
    camelot = to_camelot(key, scale)
    logger.info("Key detected: %s (Camelot: %s, strength: %.3f)", standard, camelot, strength)
    return standard, camelot, scale, strength
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_key_detect.py -v`

Expected: All PASS (only tests for pure functions — `detect_key` is tested in integration).

**Step 5: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 6: Commit**

```bash
git add server/key_detect.py tests/test_key_detect.py
git commit -m "feat(key_detect): key detection with essentia + Camelot conversion"
```

---

## Task 4: Build beat-snapping and bar-counting utilities (server/beat_utils.py)

**Goal:** Pure functions for snapping timestamps to downbeats and counting bars per segment. No ML deps — just numpy/math.

**Files:**
- Create: `server/beat_utils.py`
- Create: `tests/test_beat_utils.py`

**Step 1: Write the failing tests**

Create `tests/test_beat_utils.py`:

```python
"""Tests for server/beat_utils.py — beat-snapping and bar-counting."""

from __future__ import annotations

from server.beat_utils import count_bars, snap_to_downbeat


class TestSnapToDownbeat:
    def test_exact_match(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        assert snap_to_downbeat(1.875, downbeats) == 1.875

    def test_snaps_to_nearest(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        assert snap_to_downbeat(1.9, downbeats) == 1.875

    def test_snaps_forward(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        assert snap_to_downbeat(3.6, downbeats) == 3.75

    def test_empty_downbeats_returns_original(self) -> None:
        assert snap_to_downbeat(5.0, []) == 5.0

    def test_single_downbeat(self) -> None:
        assert snap_to_downbeat(2.0, [0.0]) == 0.0


class TestCountBars:
    def test_counts_downbeats_in_range(self) -> None:
        # 4 downbeats within [0, 7.5) at BPM=128 (1.875s per bar)
        downbeats = [0.0, 1.875, 3.75, 5.625, 7.5]
        assert count_bars(0.0, 7.5, downbeats) == 4

    def test_exclusive_end(self) -> None:
        downbeats = [0.0, 1.875, 3.75, 5.625]
        # end=3.75 excludes the downbeat at 3.75
        assert count_bars(0.0, 3.75, downbeats) == 2

    def test_empty_range_returns_zero(self) -> None:
        downbeats = [0.0, 1.875, 3.75]
        assert count_bars(10.0, 20.0, downbeats) == 0

    def test_minimum_one_bar_when_segment_exists(self) -> None:
        # Even if no downbeats land inside, if the segment spans time, return at least 1
        downbeats = [0.0, 10.0]
        assert count_bars(3.0, 7.0, downbeats) == 1

    def test_empty_downbeats(self) -> None:
        assert count_bars(0.0, 10.0, []) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_beat_utils.py -v`

Expected: FAIL with ImportError.

**Step 3: Write the implementation**

Create `server/beat_utils.py`:

```python
"""Beat-snapping and bar-counting utilities."""

from __future__ import annotations

import bisect


def snap_to_downbeat(timestamp: float, downbeats: list[float]) -> float:
    """Snap a timestamp to the nearest downbeat position.

    Returns the original timestamp if downbeats is empty.
    """
    if not downbeats:
        return timestamp

    idx = bisect.bisect_left(downbeats, timestamp)

    candidates: list[float] = []
    if idx > 0:
        candidates.append(downbeats[idx - 1])
    if idx < len(downbeats):
        candidates.append(downbeats[idx])

    return min(candidates, key=lambda d: abs(d - timestamp))


def count_bars(start: float, end: float, downbeats: list[float]) -> int:
    """Count the number of bars in a time range [start, end).

    A bar is counted for each downbeat that falls within the range.
    Returns at least 1 if the segment spans any time.
    """
    if not downbeats:
        return 1 if end > start else 0

    lo = bisect.bisect_left(downbeats, start)
    hi = bisect.bisect_left(downbeats, end)
    count = hi - lo

    return max(count, 1) if end > start else count
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_beat_utils.py -v`

Expected: All PASS.

**Step 5: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 6: Commit**

```bash
git add server/beat_utils.py tests/test_beat_utils.py
git commit -m "feat(beat_utils): beat-snapping and bar-counting utilities"
```

---

## Task 5: Build EDM reclassifier (server/edm_reclassify.py)

**Goal:** Reclassify allin1's pop-oriented segment labels into EDM terminology using per-stem RMS energy analysis from Demucs output files.

**Files:**
- Create: `server/edm_reclassify.py`
- Create: `tests/test_edm_reclassify.py`

**Step 1: Write the failing tests**

Create `tests/test_edm_reclassify.py`:

```python
"""Tests for server/edm_reclassify.py — EDM label reclassification."""

from __future__ import annotations

from server.edm_reclassify import RawSegment, reclassify_labels


class TestReclassifyLabels:
    def test_intro_stays_intro(self) -> None:
        segments = [RawSegment(label="intro", start=0.0, end=30.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Intro"

    def test_outro_stays_outro(self) -> None:
        segments = [RawSegment(label="outro", start=300.0, end=330.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Outro"

    def test_verse_stays_verse(self) -> None:
        segments = [RawSegment(label="verse", start=30.0, end=60.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Verse"

    def test_bridge_stays_bridge(self) -> None:
        segments = [RawSegment(label="bridge", start=60.0, end=90.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Bridge"

    def test_inst_becomes_instrumental(self) -> None:
        segments = [RawSegment(label="inst", start=0.0, end=30.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Instrumental"

    def test_solo_becomes_solo(self) -> None:
        segments = [RawSegment(label="solo", start=0.0, end=30.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Solo"

    def test_start_and_end_filtered_out(self) -> None:
        segments = [
            RawSegment(label="start", start=0.0, end=0.1),
            RawSegment(label="intro", start=0.1, end=30.0),
            RawSegment(label="end", start=330.0, end=330.1),
        ]
        result = reclassify_labels(segments, stem_energies=None)
        assert len(result) == 1
        assert result[0].label == "Intro"

    def test_chorus_becomes_drop_with_high_energy(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        # High drums + high bass = Drop
        energies = {(60.0, 90.0): {"drums": 0.8, "bass": 0.7}}
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Drop"

    def test_chorus_stays_chorus_with_low_energy(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        # Low drums + low bass = just Chorus
        energies = {(60.0, 90.0): {"drums": 0.2, "bass": 0.3}}
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Chorus"

    def test_break_before_drop_becomes_buildup(self) -> None:
        segments = [
            RawSegment(label="break", start=50.0, end=60.0),
            RawSegment(label="chorus", start=60.0, end=90.0),
        ]
        energies = {
            (50.0, 60.0): {"drums": 0.3, "bass": 0.2},
            (60.0, 90.0): {"drums": 0.8, "bass": 0.7},
        }
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Buildup"
        assert result[1].label == "Drop"

    def test_break_not_before_drop_becomes_breakdown(self) -> None:
        segments = [
            RawSegment(label="break", start=90.0, end=120.0),
            RawSegment(label="verse", start=120.0, end=150.0),
        ]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Breakdown"

    def test_chorus_without_energy_data_stays_chorus(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Chorus"

    def test_preserves_original_label(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        energies = {(60.0, 90.0): {"drums": 0.8, "bass": 0.7}}
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].original_label == "chorus"

    def test_numbered_labels_for_repeated_sections(self) -> None:
        segments = [
            RawSegment(label="chorus", start=60.0, end=90.0),
            RawSegment(label="break", start=90.0, end=105.0),
            RawSegment(label="chorus", start=105.0, end=135.0),
        ]
        energies = {
            (60.0, 90.0): {"drums": 0.8, "bass": 0.7},
            (90.0, 105.0): {"drums": 0.2, "bass": 0.2},
            (105.0, 135.0): {"drums": 0.8, "bass": 0.7},
        }
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Drop 1"
        assert result[2].label == "Drop 2"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_edm_reclassify.py -v`

Expected: FAIL with ImportError.

**Step 3: Write the implementation**

Create `server/edm_reclassify.py`:

```python
"""EDM reclassification of allin1 segment labels using stem energy analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# RMS energy thresholds for classifying high-energy sections
_HIGH_DRUMS_THRESHOLD = 0.5
_HIGH_BASS_THRESHOLD = 0.4

# Type alias for stem energies: {(start, end): {"drums": float, "bass": float}}
StemEnergies = dict[tuple[float, float], dict[str, float]]


@dataclass
class RawSegment:
    """A segment as returned by allin1."""

    label: str
    start: float
    end: float


@dataclass
class ClassifiedSegment:
    """A segment with EDM label and original label preserved."""

    label: str
    original_label: str
    start: float
    end: float


def _is_high_energy(
    seg: RawSegment, stem_energies: StemEnergies | None,
) -> bool:
    """Check if a segment has high drum + bass energy (indicating a drop)."""
    if stem_energies is None:
        return False
    energy = stem_energies.get((seg.start, seg.end))
    if energy is None:
        return False
    return (
        energy.get("drums", 0.0) >= _HIGH_DRUMS_THRESHOLD
        and energy.get("bass", 0.0) >= _HIGH_BASS_THRESHOLD
    )


def _classify_segment(
    seg: RawSegment,
    next_seg: RawSegment | None,
    stem_energies: StemEnergies | None,
) -> str | None:
    """Map a single allin1 label to an EDM label. Returns None to filter out."""
    label = seg.label

    if label in ("start", "end"):
        return None

    direct_map: dict[str, str] = {
        "intro": "Intro",
        "outro": "Outro",
        "verse": "Verse",
        "bridge": "Bridge",
        "inst": "Instrumental",
        "solo": "Solo",
    }

    if label in direct_map:
        return direct_map[label]

    if label == "chorus":
        if _is_high_energy(seg, stem_energies):
            return "Drop"
        return "Chorus"

    if label == "break":
        # If next segment is a high-energy chorus (drop), this break is a buildup
        if next_seg is not None and next_seg.label == "chorus":
            if _is_high_energy(next_seg, stem_energies):
                return "Buildup"
        return "Breakdown"

    # Unknown label — capitalize and pass through
    return label.capitalize()


def _number_duplicates(segments: list[ClassifiedSegment]) -> None:
    """Add numbering to repeated labels (e.g., Drop -> Drop 1, Drop 2)."""
    label_counts: dict[str, int] = {}
    for seg in segments:
        label_counts[seg.label] = label_counts.get(seg.label, 0) + 1

    labels_needing_numbers = {label for label, count in label_counts.items() if count > 1}

    counters: dict[str, int] = {}
    for seg in segments:
        if seg.label in labels_needing_numbers:
            counters[seg.label] = counters.get(seg.label, 0) + 1
            seg.label = f"{seg.label} {counters[seg.label]}"


def reclassify_labels(
    segments: list[RawSegment],
    stem_energies: StemEnergies | None,
) -> list[ClassifiedSegment]:
    """Reclassify allin1 segments into EDM-appropriate labels.

    Uses stem energy data (if available) to distinguish drops from choruses
    and buildups from breakdowns.
    """
    classified: list[ClassifiedSegment] = []

    for i, seg in enumerate(segments):
        next_seg = segments[i + 1] if i + 1 < len(segments) else None
        edm_label = _classify_segment(seg, next_seg, stem_energies)
        if edm_label is None:
            continue
        classified.append(
            ClassifiedSegment(
                label=edm_label,
                original_label=seg.label,
                start=seg.start,
                end=seg.end,
            )
        )

    _number_duplicates(classified)
    return classified
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_edm_reclassify.py -v`

Expected: All PASS.

**Step 5: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 6: Commit**

```bash
git add server/edm_reclassify.py tests/test_edm_reclassify.py
git commit -m "feat(edm_reclassify): EDM label reclassifier with stem energy analysis"
```

---

## Task 6: Build VDJ database writer (server/vdj.py)

**Goal:** Read-modify-write VDJ's database.xml to add/update scan data (BPM, key), beatgrid, and named hot cues for a track.

**Files:**
- Create: `server/vdj.py`
- Create: `tests/test_vdj.py`

**Step 1: Write the failing tests**

Create `tests/test_vdj.py`:

```python
"""Tests for server/vdj.py — Virtual DJ database.xml writer."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from server.models import AnalysisResult, SegmentInfo
from server.vdj import (
    CUE_PRIORITY,
    bpm_to_seconds_per_beat,
    build_cue_name,
    prioritize_cues,
    write_to_vdj_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal VDJ database.xml."""
    db_path = tmp_path / "database.xml"
    db_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<VirtualDJ_Database Version="8.2">\n'
        "</VirtualDJ_Database>\n"
    )
    return db_path


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        bpm=128.0,
        key="Am",
        key_camelot="8A",
        beats=[0.234, 0.703, 1.172, 1.641],
        downbeats=[0.234, 1.172],
        segments=[
            SegmentInfo(label="Intro (32 bars)", original_label="intro", start=0.234, end=60.5, bars=32),
            SegmentInfo(label="Drop 1 (16 bars)", original_label="chorus", start=60.5, end=90.5, bars=16),
            SegmentInfo(label="Breakdown (8 bars)", original_label="break", start=90.5, end=105.5, bars=8),
            SegmentInfo(label="Drop 2 (16 bars)", original_label="chorus", start=105.5, end=135.5, bars=16),
            SegmentInfo(label="Outro (16 bars)", original_label="outro", start=135.5, end=165.5, bars=16),
        ],
    )


class TestBpmConversion:
    def test_128_bpm(self) -> None:
        assert bpm_to_seconds_per_beat(128.0) == 60.0 / 128.0

    def test_140_bpm(self) -> None:
        result = bpm_to_seconds_per_beat(140.0)
        assert abs(result - 60.0 / 140.0) < 1e-10


class TestBuildCueName:
    def test_with_bars(self) -> None:
        seg = SegmentInfo(label="Drop 1", original_label="chorus", start=60.0, end=90.0, bars=16)
        assert build_cue_name(seg) == "Drop 1 (16 bars)"

    def test_single_bar(self) -> None:
        seg = SegmentInfo(label="Intro", original_label="intro", start=0.0, end=2.0, bars=1)
        assert build_cue_name(seg) == "Intro (1 bar)"


class TestPrioritizeCues:
    def test_respects_max_cues(self) -> None:
        result = _sample_result()
        cues = prioritize_cues(result.segments, max_cues=3)
        assert len(cues) == 3

    def test_drops_first(self) -> None:
        result = _sample_result()
        cues = prioritize_cues(result.segments, max_cues=2)
        # Both drops should come first
        labels = [c.label for c in cues]
        assert all("Drop" in l for l in labels)


class TestWriteToVdjDatabase:
    def test_creates_song_element(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None

    def test_writes_scan_bpm(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        scan = song.find("Scan")
        assert scan is not None
        assert float(scan.get("Bpm", "0")) == 60.0 / 128.0

    def test_writes_scan_key(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        scan = song.find("Scan")
        assert scan is not None
        assert scan.get("Key") == "Am"

    def test_writes_beatgrid_poi(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        beatgrid = song.find(".//Poi[@Type='beatgrid']")
        assert beatgrid is not None
        assert float(beatgrid.get("Pos", "0")) == 0.234

    def test_writes_cue_pois(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result, max_cues=8)

        tree = ET.parse(db_path)
        song = tree.getroot().find(".//Song[@FilePath='/path/to/track.m4a']")
        assert song is not None
        cues = [p for p in song.findall("Poi") if p.get("Type") is None and p.get("Num")]
        assert len(cues) == 5  # all 5 segments fit within 8

    def test_skips_if_db_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nonexistent" / "database.xml"
        result = _sample_result()
        # Should not raise
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)

    def test_updates_existing_song(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        result = _sample_result()
        write_to_vdj_database(db_path, "/path/to/track.m4a", result)
        # Write again with different BPM
        result2 = _sample_result()
        result2.bpm = 140.0
        write_to_vdj_database(db_path, "/path/to/track.m4a", result2)

        tree = ET.parse(db_path)
        songs = tree.getroot().findall(".//Song[@FilePath='/path/to/track.m4a']")
        assert len(songs) == 1  # no duplicate
        scan = songs[0].find("Scan")
        assert scan is not None
        assert abs(float(scan.get("Bpm", "0")) - 60.0 / 140.0) < 1e-10
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vdj.py -v`

Expected: FAIL with ImportError.

**Step 3: Write the implementation**

Create `server/vdj.py`:

```python
"""Virtual DJ database.xml writer for analysis results."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from server.models import AnalysisResult, SegmentInfo

logger = logging.getLogger(__name__)

# Priority order for filling cue slots (highest priority first)
CUE_PRIORITY: list[str] = [
    "Drop", "Buildup", "Breakdown", "Intro", "Outro", "Verse", "Bridge",
    "Instrumental", "Solo", "Chorus",
]


def bpm_to_seconds_per_beat(bpm: float) -> float:
    """Convert BPM to VDJ's seconds-per-beat format."""
    return 60.0 / bpm


def build_cue_name(segment: SegmentInfo) -> str:
    """Build a cue point name like 'Drop 1 (16 bars)'."""
    bar_word = "bar" if segment.bars == 1 else "bars"
    return f"{segment.label} ({segment.bars} {bar_word})"


def prioritize_cues(
    segments: list[SegmentInfo], max_cues: int = 8,
) -> list[SegmentInfo]:
    """Select up to max_cues segments, prioritized by DJ importance.

    Segments are sorted by priority (drops first), then by position within
    each priority level.
    """
    def priority_key(seg: SegmentInfo) -> tuple[int, float]:
        # Extract base label without numbering (e.g., "Drop 1" -> "Drop")
        base = seg.label.rsplit(" ", 1)[0] if seg.label[-1].isdigit() else seg.label
        try:
            rank = CUE_PRIORITY.index(base)
        except ValueError:
            rank = len(CUE_PRIORITY)
        return (rank, seg.start)

    sorted_segs = sorted(segments, key=priority_key)
    selected = sorted_segs[:max_cues]
    # Re-sort by position for natural cue numbering
    return sorted(selected, key=lambda s: s.start)


def write_to_vdj_database(
    db_path: Path,
    filepath: str,
    result: AnalysisResult,
    max_cues: int = 8,
) -> None:
    """Write analysis results to VDJ database.xml.

    Creates or updates the Song element for the given filepath.
    Silently skips if db_path does not exist.
    """
    if not db_path.exists():
        logger.warning("VDJ database not found at %s, skipping", db_path)
        return

    try:
        tree = ET.parse(db_path)
    except ET.ParseError:
        logger.warning("Failed to parse VDJ database at %s", db_path)
        return

    root = tree.getroot()

    # Find or create Song element
    song = root.find(f".//Song[@FilePath='{filepath}']")
    if song is None:
        song = ET.SubElement(root, "Song")
        song.set("FilePath", filepath)
    else:
        # Clear existing auto-generated POIs and Scan
        for child in list(song):
            song.remove(child)

    # Write Scan element
    scan = ET.SubElement(song, "Scan")
    scan.set("Version", "801")
    scan.set("Bpm", str(bpm_to_seconds_per_beat(result.bpm)))
    scan.set("Key", result.key)

    # Write beatgrid anchor (first downbeat)
    if result.downbeats:
        beatgrid = ET.SubElement(song, "Poi")
        beatgrid.set("Pos", str(result.downbeats[0]))
        beatgrid.set("Type", "beatgrid")

    # Write prioritized cue points
    cues = prioritize_cues(result.segments, max_cues=max_cues)
    for i, seg in enumerate(cues, start=1):
        poi = ET.SubElement(song, "Poi")
        poi.set("Name", build_cue_name(seg))
        poi.set("Pos", str(seg.start))
        poi.set("Num", str(i))

    # Write back
    tree.write(str(db_path), encoding="UTF-8", xml_declaration=True)
    logger.info("Wrote %d cue points to VDJ database for %s", len(cues), filepath)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vdj.py -v`

Expected: All PASS.

**Step 5: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 6: Commit**

```bash
git add server/vdj.py tests/test_vdj.py
git commit -m "feat(vdj): Virtual DJ database.xml writer with prioritized cue points"
```

---

## Task 7: Build analyzer orchestrator (server/analyzer.py)

**Goal:** Orchestrate the full 5-stage analysis pipeline. Calls allin1, essentia key detection, EDM reclassifier, bar counting, beat-snapping, and VDJ writer.

**Files:**
- Create: `server/analyzer.py`
- Create: `tests/test_analyzer.py`

**Step 1: Write the failing tests**

Create `tests/test_analyzer.py`. Since allin1 and essentia are heavy ML deps, we mock them and test the orchestration logic:

```python
"""Tests for server/analyzer.py — analysis pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.analyzer import analyze_audio
from server.models import AnalysisResult


@dataclass
class MockAllin1Segment:
    label: str
    start: float
    end: float


@dataclass
class MockAllin1Result:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    beat_positions: list[int]
    segments: list[MockAllin1Segment]


def _mock_allin1_result() -> MockAllin1Result:
    """Simulate allin1.analyze() output for a 128 BPM track."""
    return MockAllin1Result(
        bpm=128.0,
        beats=[0.0 + i * 0.46875 for i in range(64)],
        downbeats=[0.0 + i * 1.875 for i in range(16)],
        beat_positions=[((i % 4) + 1) for i in range(64)],
        segments=[
            MockAllin1Segment(label="start", start=0.0, end=0.0),
            MockAllin1Segment(label="intro", start=0.0, end=7.5),
            MockAllin1Segment(label="chorus", start=7.5, end=15.0),
            MockAllin1Segment(label="break", start=15.0, end=18.75),
            MockAllin1Segment(label="chorus", start=18.75, end=26.25),
            MockAllin1Segment(label="outro", start=26.25, end=30.0),
            MockAllin1Segment(label="end", start=30.0, end=30.0),
        ],
    )


@pytest.fixture
def mock_allin1() -> Any:
    with patch("server.analyzer.allin1") as mock:
        mock.analyze.return_value = _mock_allin1_result()
        yield mock


@pytest.fixture
def mock_key_detect() -> Any:
    with patch("server.analyzer.detect_key", new_callable=AsyncMock) as mock:
        mock.return_value = ("Am", "8A", "minor", 0.87)
        yield mock


@pytest.fixture
def mock_stem_energies() -> Any:
    with patch("server.analyzer._compute_stem_energies") as mock:
        # Return high energy for chorus segments, low for others
        mock.return_value = {
            (7.5, 15.0): {"drums": 0.8, "bass": 0.7},
            (18.75, 26.25): {"drums": 0.8, "bass": 0.7},
        }
        yield mock


async def test_analyze_returns_result(
    tmp_path: Path, mock_allin1: Any, mock_key_detect: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    result = await analyze_audio(filepath)
    assert isinstance(result, AnalysisResult)
    assert result.bpm == 128.0
    assert result.key == "Am"
    assert result.key_camelot == "8A"


async def test_segments_reclassified_to_edm(
    tmp_path: Path, mock_allin1: Any, mock_key_detect: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    result = await analyze_audio(filepath)
    labels = [s.label for s in result.segments]
    assert "Intro" in labels[0]
    # Chorus with high energy should become Drop
    assert any("Drop" in l for l in labels)


async def test_segments_have_bar_counts(
    tmp_path: Path, mock_allin1: Any, mock_key_detect: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    result = await analyze_audio(filepath)
    for seg in result.segments:
        assert seg.bars >= 1


async def test_allin1_failure_returns_none(tmp_path: Path, mock_key_detect: Any) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    with patch("server.analyzer.allin1") as mock:
        mock.analyze.side_effect = RuntimeError("NATTEN crash")
        result = await analyze_audio(filepath)
    assert result is None


async def test_key_detect_failure_uses_unknown(
    tmp_path: Path, mock_allin1: Any, mock_stem_energies: Any
) -> None:
    filepath = tmp_path / "track.m4a"
    filepath.touch()
    with patch("server.analyzer.detect_key", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("essentia error")
        result = await analyze_audio(filepath)
    assert result is not None
    assert result.key == ""
    assert result.key_camelot == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyzer.py -v`

Expected: FAIL with ImportError.

**Step 3: Write the implementation**

Create `server/analyzer.py`:

```python
"""Audio analysis pipeline orchestrator.

Stages:
1. Structure analysis (allin1) — segments, beats, downbeats, BPM
2. Key detection (essentia) — key, Camelot notation
3. EDM reclassification — drop/buildup/breakdown from stem energy
4. Bar counting — downbeats per segment
5. Beat-snapping — align segment boundaries to downbeats
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import allin1  # type: ignore[import-untyped]

from server.beat_utils import count_bars, snap_to_downbeat
from server.edm_reclassify import RawSegment, StemEnergies, reclassify_labels
from server.key_detect import detect_key
from server.models import AnalysisResult, SegmentInfo

logger = logging.getLogger(__name__)


def _compute_stem_energies(
    filepath: Path,
    segments: list[RawSegment],
    demix_dir: Path,
) -> StemEnergies | None:
    """Compute per-stem RMS energy for each segment from Demucs output.

    Returns None if stems are not available.
    """
    import numpy as np

    # allin1 saves stems as: demix_dir / model_name / track_name / {drums,bass,...}.wav
    # Find the stem directory
    stem_dirs = list(demix_dir.glob("*/"))
    if not stem_dirs:
        logger.warning("No Demucs output found in %s", demix_dir)
        return None

    track_name = filepath.stem
    track_dirs: list[Path] = []
    for model_dir in stem_dirs:
        candidate = model_dir / track_name
        if candidate.is_dir():
            track_dirs.append(candidate)

    if not track_dirs:
        logger.warning("No stem directory found for %s in %s", track_name, demix_dir)
        return None

    stem_dir = track_dirs[0]
    drums_path = stem_dir / "drums.wav"
    bass_path = stem_dir / "bass.wav"

    if not drums_path.exists() or not bass_path.exists():
        logger.warning("drums.wav or bass.wav not found in %s", stem_dir)
        return None

    try:
        import soundfile as sf  # type: ignore[import-untyped]

        drums_audio: Any
        drums_sr: int
        drums_audio, drums_sr = sf.read(str(drums_path))
        bass_audio: Any
        bass_sr: int
        bass_audio, bass_sr = sf.read(str(bass_path))
    except Exception:
        logger.warning("Failed to load stem audio files", exc_info=True)
        return None

    # Convert stereo to mono if needed
    if drums_audio.ndim > 1:
        drums_audio = np.mean(drums_audio, axis=1)
    if bass_audio.ndim > 1:
        bass_audio = np.mean(bass_audio, axis=1)

    energies: StemEnergies = {}
    for seg in segments:
        if seg.label in ("start", "end"):
            continue
        start_sample = int(seg.start * drums_sr)
        end_sample = int(seg.end * drums_sr)

        drums_slice: Any = drums_audio[start_sample:end_sample]
        bass_slice: Any = bass_audio[start_sample:end_sample]

        if len(drums_slice) == 0 or len(bass_slice) == 0:
            continue

        drums_rms: float = float(np.sqrt(np.mean(drums_slice**2)))
        bass_rms: float = float(np.sqrt(np.mean(bass_slice**2)))

        energies[(seg.start, seg.end)] = {"drums": drums_rms, "bass": bass_rms}

    return energies


def _run_allin1_sync(filepath: Path, demix_dir: Path) -> Any:
    """Run allin1 analysis synchronously."""
    return allin1.analyze(
        str(filepath),
        keep_byproducts=True,
        demix_dir=str(demix_dir),
    )


async def analyze_audio(
    filepath: Path,
    vdj_db_path: Path | None = None,
    max_cues: int = 8,
) -> AnalysisResult | None:
    """Run the full 5-stage analysis pipeline.

    Returns AnalysisResult on success, None on failure.
    Never raises — all errors are caught and logged.
    """
    import tempfile

    demix_dir = Path(tempfile.mkdtemp(prefix="dj-kompanion-demix-"))

    # --- Stage 1: Structure analysis (allin1) ---
    try:
        allin1_result: Any = await asyncio.to_thread(_run_allin1_sync, filepath, demix_dir)
    except Exception:
        logger.error("allin1 analysis failed for %s", filepath, exc_info=True)
        return None

    bpm: float = float(allin1_result.bpm)
    beats: list[float] = [float(b) for b in allin1_result.beats]
    downbeats: list[float] = [float(d) for d in allin1_result.downbeats]

    raw_segments = [
        RawSegment(label=str(seg.label), start=float(seg.start), end=float(seg.end))
        for seg in allin1_result.segments
    ]

    # --- Stage 2: Key detection (essentia) ---
    key = ""
    key_camelot = ""
    try:
        key, key_camelot, _scale, _strength = await detect_key(filepath)
    except Exception:
        logger.warning("Key detection failed for %s, continuing without key", filepath, exc_info=True)

    # --- Stage 3: EDM reclassification ---
    stem_energies: StemEnergies | None = None
    try:
        stem_energies = await asyncio.to_thread(
            _compute_stem_energies, filepath, raw_segments, demix_dir,
        )
    except Exception:
        logger.warning("Stem energy computation failed, using default labels", exc_info=True)

    classified = reclassify_labels(raw_segments, stem_energies)

    # --- Stage 4: Bar counting ---
    # --- Stage 5: Beat-snapping ---
    segments: list[SegmentInfo] = []
    for seg in classified:
        snapped_start = snap_to_downbeat(seg.start, downbeats)
        snapped_end = snap_to_downbeat(seg.end, downbeats)
        bars = count_bars(snapped_start, snapped_end, downbeats)
        segments.append(
            SegmentInfo(
                label=seg.label,
                original_label=seg.original_label,
                start=snapped_start,
                end=snapped_end,
                bars=bars,
            )
        )

    result = AnalysisResult(
        bpm=bpm,
        key=key,
        key_camelot=key_camelot,
        beats=beats,
        downbeats=downbeats,
        segments=segments,
        vdj_written=False,
    )

    # --- Write to VDJ database ---
    if vdj_db_path is not None:
        try:
            from server.vdj import write_to_vdj_database

            write_to_vdj_database(vdj_db_path, str(filepath), result, max_cues=max_cues)
            result.vdj_written = True
        except Exception:
            logger.warning("Failed to write to VDJ database", exc_info=True)

    # Cleanup demix dir
    try:
        import shutil

        shutil.rmtree(demix_dir, ignore_errors=True)
    except Exception:
        pass

    logger.info(
        "Analysis complete for %s: BPM=%.1f, Key=%s, %d segments",
        filepath, bpm, key, len(segments),
    )
    return result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_analyzer.py -v`

Expected: All PASS.

**Step 5: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 6: Commit**

```bash
git add server/analyzer.py tests/test_analyzer.py
git commit -m "feat(analyzer): 5-stage audio analysis pipeline orchestrator"
```

---

## Task 8: Add /api/analyze endpoint and post-download trigger

**Goal:** Add `POST /api/analyze` endpoint and fire analysis as a background task after download completes.

**Files:**
- Modify: `server/config.py`
- Modify: `server/app.py`
- Modify: `server/models.py` (add AnalyzeResponse to imports if needed)
- Modify: `tests/test_app.py`

**Step 1: Add VDJ config**

In `server/config.py`, add VDJ database path to AppConfig:

```python
class AnalysisConfig(BaseModel):
    enabled: bool = True
    vdj_database: Path = Path("~/Documents/VirtualDJ/database.xml").expanduser()
    max_cues: int = 8


class AppConfig(BaseModel):
    output_dir: Path = Path("~/Music/DJ Library").expanduser()
    preferred_format: str = "best"
    filename_template: str = "{artist} - {title}"
    server_port: int = 9234
    llm: LLMConfig = LLMConfig()
    analysis: AnalysisConfig = AnalysisConfig()
```

Update `_serializable_defaults` to include analysis config:

```python
def _serializable_defaults() -> dict[str, object]:
    config = AppConfig()
    data = config.model_dump()
    data["output_dir"] = str(config.output_dir)
    data["analysis"] = {
        "enabled": config.analysis.enabled,
        "vdj_database": str(config.analysis.vdj_database),
        "max_cues": config.analysis.max_cues,
    }
    return data
```

**Step 2: Write failing tests for /api/analyze**

Add to `tests/test_app.py`:

```python
from server.models import AnalysisResult, SegmentInfo

SAMPLE_ANALYSIS = AnalysisResult(
    bpm=128.0,
    key="Am",
    key_camelot="8A",
    beats=[0.234],
    downbeats=[0.234],
    segments=[
        SegmentInfo(label="Intro (32 bars)", original_label="intro", start=0.234, end=60.5, bars=32),
    ],
    vdj_written=False,
)


async def test_analyze_success(client: AsyncClient) -> None:
    with (
        patch("server.app.FilePath") as mock_fp_cls,
        patch("server.app.analyze_audio", new_callable=AsyncMock, return_value=SAMPLE_ANALYSIS),
    ):
        mock_fp_cls.return_value.exists.return_value = True
        response = await client.post("/api/analyze", json={"filepath": "/path/to/track.m4a"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["analysis"]["bpm"] == 128.0
    assert data["analysis"]["key"] == "Am"


async def test_analyze_file_not_found(client: AsyncClient) -> None:
    with patch("server.app.FilePath") as mock_fp_cls:
        mock_fp_cls.return_value.exists.return_value = False
        response = await client.post("/api/analyze", json={"filepath": "/nonexistent.m4a"})
    assert response.status_code == 404
    assert response.json()["error"] == "file_not_found"


async def test_analyze_failure(client: AsyncClient) -> None:
    with (
        patch("server.app.FilePath") as mock_fp_cls,
        patch("server.app.analyze_audio", new_callable=AsyncMock, return_value=None),
    ):
        mock_fp_cls.return_value.exists.return_value = True
        response = await client.post("/api/analyze", json={"filepath": "/path/to/track.m4a"})
    assert response.status_code == 500
    assert response.json()["error"] == "analysis_failed"
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py::test_analyze_success -v`

Expected: FAIL.

**Step 4: Add the endpoint and post-download trigger**

In `server/app.py`:

1. Import `analyze_audio` and new models:
```python
from server.analyzer import analyze_audio
from server.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    # ... existing imports ...
)
```

2. Add the analyze endpoint:
```python
@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    filepath = FilePath(req.filepath)
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "file_not_found", "message": f"File not found: {req.filepath}"},
        )

    cfg = load_config()
    vdj_path = cfg.analysis.vdj_database if cfg.analysis.enabled else None
    result = await analyze_audio(filepath, vdj_db_path=vdj_path, max_cues=cfg.analysis.max_cues)

    if result is None:
        raise HTTPException(
            status_code=500,
            detail={"error": "analysis_failed", "message": "Audio analysis failed"},
        )

    return AnalyzeResponse(status="ok", analysis=result)
```

3. In the download endpoint, after `tag_file` succeeds and before return, fire analysis as a background task:
```python
    # Fire-and-forget analysis (non-blocking)
    cfg_analysis = cfg.analysis
    if cfg_analysis.enabled:
        import asyncio

        async def _run_analysis() -> None:
            try:
                vdj_path = cfg_analysis.vdj_database
                await analyze_audio(final_path, vdj_db_path=vdj_path, max_cues=cfg_analysis.max_cues)
            except Exception:
                logger.warning("Post-download analysis failed for %s", final_path, exc_info=True)

        asyncio.create_task(_run_analysis())
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`

Expected: All PASS (including new analyze tests + existing tests unchanged).

**Step 6: Verify mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 7: Commit**

```bash
git add server/config.py server/app.py tests/test_app.py
git commit -m "feat(api): add /api/analyze endpoint + post-download analysis trigger"
```

---

## Task 9: Update extension types, API, and queue status display

**Goal:** Add analysis-related types to the extension, add `requestAnalyze` API call, and update queue item display to show analysis status.

**Files:**
- Modify: `extension/src/types.ts`
- Modify: `extension/src/api.ts`
- Modify: `extension/src/background.ts`
- Modify: `extension/src/popup.ts`

**Step 1: Add analysis types**

In `extension/src/types.ts`, add:

```typescript
export interface SegmentInfo {
  label: string;
  original_label: string;
  start: number;
  end: number;
  bars: number;
}

export interface AnalysisResult {
  bpm: number;
  key: string;
  key_camelot: string;
  beats: number[];
  downbeats: number[];
  segments: SegmentInfo[];
  vdj_written: boolean;
}

export interface AnalyzeResponse {
  status: string;
  analysis: AnalysisResult;
}
```

Update `QueueItem` to include analysis status:

```typescript
export interface QueueItem {
  id: string;
  url: string;
  metadata: EnrichedMetadata;
  raw: RawMetadata;
  format: string;
  userEditedFields: string[];
  status: "pending" | "downloading" | "complete" | "analyzing" | "analyzed" | "error";
  enrichmentSource?: "claude" | "basic" | "none";
  filepath?: string;
  error?: string;
  addedAt: number;
  analysis?: AnalysisResult;
}
```

**Step 2: Add requestAnalyze to api.ts**

In `extension/src/api.ts`, add:

```typescript
import type { AnalyzeResponse } from "./types.js";

export async function requestAnalyze(filepath: string): Promise<AnalyzeResponse> {
  const baseUrl = await getBaseUrl();
  const response = await fetchWithTimeout(
    `${baseUrl}/api/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filepath }),
    },
    300000 // 5 min timeout for ML analysis
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as AnalyzeResponse;
}
```

**Step 3: Trigger analysis after download in background.ts**

In the `processQueue` function in `background.ts`, after a successful download, trigger analysis:

```typescript
import { requestAnalyze } from "./api.js";

// After the download succeeds and item is marked "complete":
// Fire analysis as a separate step
if (result.filepath) {
  await updateItem(pending.id, { status: "analyzing" });
  try {
    const analyzeResult = await requestAnalyze(result.filepath);
    await updateItem(pending.id, {
      status: "analyzed",
      analysis: analyzeResult.analysis,
    });
  } catch (err) {
    // Analysis failure is non-fatal — keep the download as complete
    await updateItem(pending.id, {
      status: "complete",
      error: `Analysis failed: ${err instanceof Error ? err.message : String(err)}`,
    });
  }
}
```

**Step 4: Update popup to display analysis info**

In `popup.ts`, update the queue item renderer to show analysis status:

- `analyzing`: Show spinner + "Analyzing..."
- `analyzed`: Show BPM, key, and segment summary (e.g., "128 BPM | Am (8A) | 5 sections")
- `complete` with no analysis: Show download info only

When expanded, show the segment list:
```
Intro (32 bars) | 0:00
Drop 1 (16 bars) | 1:00
Breakdown (8 bars) | 1:30
Drop 2 (16 bars) | 1:45
Outro (16 bars) | 2:15
```

**Step 5: Update badge to include analyzing state**

In `background.ts`, update `updateBadge` to count `analyzing` as active:

```typescript
const active = queue.filter(
  (i) => i.status === "pending" || i.status === "downloading" || i.status === "analyzing"
).length;
```

**Step 6: Update stale recovery to handle analyzing state**

```typescript
if (item.status === "downloading" || item.status === "analyzing") {
  item.status = "pending";
  changed = true;
}
```

**Step 7: Verify**

```bash
cd extension && npx tsc --noEmit && npm run build && npm run lint
```

**Step 8: Commit**

```bash
git add extension/src/types.ts extension/src/api.ts extension/src/background.ts extension/src/popup.ts
git commit -m "feat(extension): analysis status display + requestAnalyze API"
```

---

## Task 10: Integration test — end-to-end verify

**Goal:** Verify the full stack builds, typechecks, lints, and tests pass.

**Files:**
- No changes — verification only.

**Step 1: Python tests**

Run: `uv run pytest -x -v`

Expected: All PASS.

**Step 2: Python mypy**

Run: `uv run mypy server/`

Expected: No errors.

**Step 3: Python lint**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: Clean.

**Step 4: Extension typecheck**

Run: `cd extension && npx tsc --noEmit`

Expected: No errors.

**Step 5: Extension build**

Run: `cd extension && npm run build`

Expected: Build succeeds.

**Step 6: Extension lint**

Run: `cd extension && npm run lint`

Expected: Clean.

**Step 7: Manual smoke test checklist**

1. Start server: `uv run uvicorn server.app:app --reload --port 9234`
2. Load extension in Chrome
3. Download a track via the extension
4. Verify in server logs that analysis runs after download
5. If VDJ database exists at `~/Documents/VirtualDJ/database.xml`:
   - Open VDJ, load the track
   - Verify cue points appear with labels like "Drop 1 (16 bars)"
   - Verify BPM and key are set
6. Test `/api/analyze` directly:
   ```bash
   curl -X POST http://localhost:9234/api/analyze \
     -H "Content-Type: application/json" \
     -d '{"filepath": "/path/to/downloaded/track.m4a"}'
   ```
7. Verify extension shows analysis status progression:
   pending -> downloading -> complete -> analyzing -> analyzed

---

## Outcomes & Retrospective

_Filled by /harness:complete when work is done._

**What worked:**
-

**What didn't:**
-

**Learnings to codify:**
-
