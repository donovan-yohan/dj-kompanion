# Dockerized Analyzer Microservice Implementation Plan

> **Status**: Completed | **Created**: 2026-02-28 | **Completed**: 2026-02-28
> **Design Doc**: `docs/design-docs/2026-02-28-dockerized-analyzer-design.md`
> **For Claude:** Use /harness:orchestrate to execute this plan.

**Goal:** Extract the allin1 analysis pipeline into a standalone Docker container so it runs on macOS ARM64 (where NATTEN has no native wheels), and refactor the main server's analyzer.py into a thin HTTP client that calls the container.

**Architecture:** A new `analyzer/` directory contains a self-contained FastAPI service with the 5-stage pipeline (allin1, essentia key detection, EDM reclassify, bar count, beat-snap). The main server's `server/analyzer.py` becomes an HTTP client using httpx. docker-compose.yml defines the analyzer service with a read-only volume mount for the audio output directory.

**Tech Stack:** Docker, FastAPI, allin1, essentia, madmom, httpx (new dep for main server), pydantic.

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-02-28 | Design | Separate container for analysis only | Keeps Claude CLI working natively; analysis is the only part needing Linux |
| 2026-02-28 | Design | Volume mount over file upload | Audio files already on disk; no upload overhead |
| 2026-02-28 | Design | Main server owns VDJ write | Container stays read-only; clean separation |
| 2026-02-28 | Design | Configurable analyzer URL | Allows pointing to remote analyzer or different port |
| 2026-02-28 | Retrospective | Plan completed — 8/8 tasks, 0 drift, 3 surprises | Clean execution; parallel workers effective for independent tasks |

## Progress

- [x] Task 1: Create analyzer container models and utilities _(completed 2026-02-28)_
- [x] Task 2: Build analyzer container FastAPI app _(completed 2026-02-28)_
- [x] Task 3: Create Dockerfile and docker-compose.yml _(completed 2026-02-28)_
- [x] Task 4: Refactor main server analyzer.py to HTTP client _(completed 2026-02-28)_
- [x] Task 5: Add analyzer_url to config and update /api/analyze endpoint _(completed 2026-02-28)_
- [x] Task 6: Clean up main server dependencies _(completed 2026-02-28)_
- [x] Task 7: Update README and docs _(completed 2026-02-28)_
- [x] Task 8: Integration test — end-to-end verify _(completed 2026-02-28)_

## Surprises & Discoveries

| Date | What was unexpected | How it affects the plan | What was done |
|------|---------------------|------------------------|---------------|
| 2026-02-28 | Worker 1 committed worker 2's files (app.py, pipeline.py) in same commit | No impact — files were identical, no conflicts | Both workers verified content matched; single combined commit ebf1dd7 |
| 2026-02-28 | VDJ test must patch at source (server.vdj) not at import site (server.analyzer) | No impact — lazy import means attribute doesn't exist on analyzer module | Patched server.vdj.write_to_vdj_database instead |
| 2026-02-28 | System Python is 3.14, essentia only has wheels up to 3.13 | Tests need `--python 3.13` flag; will be moot after Task 6 removes essentia from main server | Pre-existing issue, not introduced by this work |

## Plan Drift

_None yet — updated when tasks deviate from plan during execution._

---

## Task 1: Create analyzer container models and utilities

**Goal:** Copy the analysis-specific code into the `analyzer/` directory as self-contained modules. These are copies, not symlinks — the container is fully independent from the main server.

**Files:**
- Create: `analyzer/models.py`
- Create: `analyzer/key_detect.py`
- Create: `analyzer/beat_utils.py`
- Create: `analyzer/edm_reclassify.py`

**Step 1: Create analyzer/models.py**

Copy `SegmentInfo` and `AnalysisResult` from `server/models.py`. Also add request/response models for the container's API.

```python
from __future__ import annotations

from pydantic import BaseModel


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


class AnalyzeRequest(BaseModel):
    filepath: str


class AnalyzeResponse(BaseModel):
    status: str
    analysis: AnalysisResult | None = None
    message: str | None = None
```

**Step 2: Copy beat_utils.py**

Copy `server/beat_utils.py` verbatim to `analyzer/beat_utils.py`. Change nothing — the module has no server-specific imports.

**Step 3: Copy key_detect.py**

Copy `server/key_detect.py` to `analyzer/key_detect.py`. Change nothing — it only imports essentia and asyncio.

**Step 4: Copy edm_reclassify.py**

Copy `server/edm_reclassify.py` to `analyzer/edm_reclassify.py`. Change nothing — it has no server-specific imports.

**Step 5: Verify all modules are self-contained**

Run: `python -c "import ast; [ast.parse(open(f'analyzer/{f}').read()) for f in ['models.py','beat_utils.py','key_detect.py','edm_reclassify.py']]; print('OK')"`

Expected: `OK` — all files parse without syntax errors.

---

## Task 2: Build analyzer container FastAPI app

**Goal:** Create the FastAPI application for the analyzer container. This is a simplified version of `server/analyzer.py` wrapped in an HTTP endpoint.

**Files:**
- Create: `analyzer/app.py`
- Create: `analyzer/pipeline.py` (the 5-stage orchestrator, adapted from `server/analyzer.py`)

**Step 1: Create analyzer/pipeline.py**

Adapt `server/analyzer.py` into `analyzer/pipeline.py`. Key differences from the original:
- Import from `analyzer.*` instead of `server.*`
- No `vdj_written` field (VDJ write is the main server's job)
- No `vdj_db_path` or `max_cues` parameters
- allin1 is imported directly (no try/except — in the container it must work)

```python
"""5-stage audio analysis pipeline for the analyzer container."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import allin1

from analyzer.beat_utils import count_bars, snap_to_downbeat
from analyzer.edm_reclassify import RawSegment, StemEnergies, reclassify_labels
from analyzer.key_detect import detect_key
from analyzer.models import AnalysisResult, SegmentInfo

logger = logging.getLogger(__name__)


def _compute_stem_energies(
    filepath: Path,
    segments: list[RawSegment],
    demix_dir: Path,
) -> StemEnergies | None:
    """Compute per-stem RMS energy for each segment from Demucs output."""
    import numpy as np

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
        import soundfile as sf

        drums_audio: Any
        drums_sr: int
        drums_audio, drums_sr = sf.read(str(drums_path))
        bass_audio: Any
        bass_sr: int
        bass_audio, bass_sr = sf.read(str(bass_path))
    except Exception:
        logger.warning("Failed to load stem audio files", exc_info=True)
        return None

    if drums_sr != bass_sr:
        logger.warning("Stem sample rate mismatch: drums=%d, bass=%d", drums_sr, bass_sr)
        return None

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


async def run_pipeline(filepath: Path) -> AnalysisResult:
    """Run the full 5-stage analysis pipeline.

    Raises on allin1 failure (caller handles error response).
    Key detection and reclassification failures are caught and degraded gracefully.
    """
    demix_dir = Path(tempfile.mkdtemp(prefix="analyzer-demix-"))

    try:
        # Stage 1: Structure analysis (allin1)
        allin1_result: Any = await asyncio.to_thread(_run_allin1_sync, filepath, demix_dir)

        bpm: float = float(allin1_result.bpm)
        beats: list[float] = [float(b) for b in allin1_result.beats]
        downbeats: list[float] = [float(d) for d in allin1_result.downbeats]

        raw_segments = [
            RawSegment(label=str(seg.label), start=float(seg.start), end=float(seg.end))
            for seg in allin1_result.segments
        ]

        # Stage 2: Key detection (essentia)
        key = ""
        key_camelot = ""
        try:
            key, key_camelot, _scale, _strength = await detect_key(filepath)
        except Exception:
            logger.warning("Key detection failed for %s, continuing without key", filepath, exc_info=True)

        # Stage 3: EDM reclassification
        stem_energies: StemEnergies | None = None
        try:
            stem_energies = await asyncio.to_thread(
                _compute_stem_energies, filepath, raw_segments, demix_dir,
            )
        except Exception:
            logger.warning("Stem energy computation failed, using default labels", exc_info=True)

        classified = reclassify_labels(raw_segments, stem_energies)

        # Stage 4 & 5: Bar counting + Beat-snapping
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

        return AnalysisResult(
            bpm=bpm,
            key=key,
            key_camelot=key_camelot,
            beats=beats,
            downbeats=downbeats,
            segments=segments,
        )
    finally:
        shutil.rmtree(demix_dir, ignore_errors=True)
```

**Step 2: Create analyzer/app.py**

```python
"""Analyzer microservice — runs the allin1 analysis pipeline in a Docker container."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from analyzer.models import AnalyzeRequest, AnalyzeResponse
from analyzer.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="dj-kompanion-analyzer", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    filepath = Path(req.filepath)
    if not filepath.exists():
        return AnalyzeResponse(status="error", message=f"File not found: {req.filepath}")

    try:
        result = await run_pipeline(filepath)
    except Exception:
        logger.error("Analysis failed for %s", req.filepath, exc_info=True)
        return AnalyzeResponse(status="error", message="Analysis pipeline failed")

    return AnalyzeResponse(status="ok", analysis=result)
```

**Step 3: Verify syntax**

Run: `python -c "import ast; [ast.parse(open(f'analyzer/{f}').read()) for f in ['app.py','pipeline.py']]; print('OK')"`

Expected: `OK`

---

## Task 3: Create Dockerfile and docker-compose.yml

**Goal:** Create the Docker build and compose files for the analyzer container.

**Files:**
- Create: `analyzer/requirements.txt`
- Create: `analyzer/Dockerfile`
- Create: `docker-compose.yml`
- Create: `analyzer/.dockerignore`

**Step 1: Create analyzer/requirements.txt**

```
fastapi
uvicorn
numpy
soundfile
pydantic
essentia
```

Note: `allin1` and `madmom` need special install handling (git sources, Cython build deps) — these go in the Dockerfile directly.

**Step 2: Create analyzer/Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for audio processing and building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install madmom from git (broken on pip release for Python 3.11+)
RUN pip install --no-cache-dir Cython numpy && \
    pip install --no-cache-dir git+https://github.com/CPJKU/madmom.git

# Install allin1 from git (needs NATTEN which works on Linux)
RUN pip install --no-cache-dir git+https://github.com/hordiales/all-in-one.git

# Copy analyzer code
COPY . .

EXPOSE 9235

CMD ["uvicorn", "analyzer.app:app", "--host", "0.0.0.0", "--port", "9235"]
```

**Step 3: Create analyzer/.dockerignore**

```
__pycache__
*.pyc
.pytest_cache
```

**Step 4: Create docker-compose.yml** (project root)

```yaml
services:
  analyzer:
    build: ./analyzer
    ports:
      - "9235:9235"
    volumes:
      - ~/Music/DJ Library:/audio:ro
    restart: unless-stopped
```

**Step 5: Verify Dockerfile builds**

Run: `docker compose build`

Expected: Image builds successfully. This may take several minutes on first build due to PyTorch and Demucs downloads.

**Step 6: Verify container starts and responds to health check**

Run: `docker compose up -d && sleep 5 && curl http://localhost:9235/health`

Expected: `{"status":"ok"}`

Run: `docker compose down`

---

## Task 4: Refactor main server analyzer.py to HTTP client

**Goal:** Replace the direct allin1 import in `server/analyzer.py` with an HTTP call to the analyzer container. Add `httpx` as a dependency.

**Files:**
- Modify: `pyproject.toml` (add httpx)
- Modify: `server/analyzer.py` (rewrite to HTTP client)
- Modify: `tests/test_analyzer.py` (update tests for new behavior)

**Step 1: Add httpx to pyproject.toml dependencies**

In `pyproject.toml`, add `"httpx"` to `[project] dependencies`:

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
    "numpy",
    "soundfile",
    "essentia",
    "madmom",
    "allin1",
]
```

Run: `uv sync`

Note: allin1, essentia, madmom, numpy, soundfile remain in pyproject.toml for now — they're needed by other tests and type checking. Task 6 addresses cleanup.

**Step 2: Rewrite server/analyzer.py**

Replace the entire file with an HTTP client that calls the analyzer container:

```python
"""Audio analysis client — proxies requests to the analyzer container."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from server.models import AnalysisResult

logger = logging.getLogger(__name__)

# Default timeout: 10 minutes (ML analysis is slow, especially first run with model download)
_ANALYZE_TIMEOUT = 600.0


async def analyze_audio(
    filepath: Path,
    vdj_db_path: Path | None = None,
    max_cues: int = 8,
    analyzer_url: str = "http://localhost:9235",
    output_dir: Path | None = None,
) -> AnalysisResult | None:
    """Request audio analysis from the analyzer container.

    Translates the host filepath to the container's /audio mount path,
    calls the analyzer service, and optionally writes results to VDJ database.

    Returns AnalysisResult on success, None on failure.
    Never raises — all errors are caught and logged.
    """
    # Translate host path to container path
    container_path = _to_container_path(filepath, output_dir)

    try:
        async with httpx.AsyncClient(timeout=_ANALYZE_TIMEOUT) as client:
            response = await client.post(
                f"{analyzer_url}/analyze",
                json={"filepath": container_path},
            )
    except httpx.ConnectError:
        logger.error(
            "Cannot reach analyzer service at %s — is the container running? "
            "(docker compose up -d)",
            analyzer_url,
        )
        return None
    except Exception:
        logger.error("Failed to call analyzer service", exc_info=True)
        return None

    if response.status_code != 200:
        logger.error("Analyzer returned HTTP %d: %s", response.status_code, response.text)
        return None

    data = response.json()
    if data.get("status") != "ok" or data.get("analysis") is None:
        logger.error("Analyzer returned error: %s", data.get("message", "unknown"))
        return None

    result = AnalysisResult.model_validate(data["analysis"])

    # VDJ write stays in the main server
    if vdj_db_path is not None:
        try:
            from server.vdj import write_to_vdj_database

            write_to_vdj_database(vdj_db_path, str(filepath), result, max_cues=max_cues)
            result.vdj_written = True
        except Exception:
            logger.warning("Failed to write to VDJ database", exc_info=True)

    logger.info(
        "Analysis complete for %s: BPM=%.1f, Key=%s, %d segments",
        filepath,
        result.bpm,
        result.key,
        len(result.segments),
    )
    return result


def _to_container_path(filepath: Path, output_dir: Path | None) -> str:
    """Translate a host filepath to the container's /audio mount path.

    Example: ~/Music/DJ Library/Artist - Title.m4a -> /audio/Artist - Title.m4a
    """
    if output_dir is not None:
        try:
            relative = filepath.relative_to(output_dir)
            return f"/audio/{relative}"
        except ValueError:
            pass
    # Fallback: use filename only
    return f"/audio/{filepath.name}"
```

**Step 3: Rewrite tests/test_analyzer.py**

Replace the existing tests to test the HTTP client behavior:

```python
"""Tests for server/analyzer.py — HTTP client for analyzer container."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from server.analyzer import _to_container_path, analyze_audio


SAMPLE_ANALYSIS_JSON = {
    "status": "ok",
    "analysis": {
        "bpm": 128.0,
        "key": "Am",
        "key_camelot": "8A",
        "beats": [0.234, 0.703],
        "downbeats": [0.234],
        "segments": [
            {
                "label": "Intro",
                "original_label": "intro",
                "start": 0.234,
                "end": 60.5,
                "bars": 32,
            }
        ],
    },
}


def test_to_container_path_with_output_dir() -> None:
    filepath = Path("/Users/me/Music/DJ Library/Artist - Title.m4a")
    output_dir = Path("/Users/me/Music/DJ Library")
    assert _to_container_path(filepath, output_dir) == "/audio/Artist - Title.m4a"


def test_to_container_path_subdirectory() -> None:
    filepath = Path("/Users/me/Music/DJ Library/EDM/Artist - Title.m4a")
    output_dir = Path("/Users/me/Music/DJ Library")
    assert _to_container_path(filepath, output_dir) == "/audio/EDM/Artist - Title.m4a"


def test_to_container_path_fallback_no_output_dir() -> None:
    filepath = Path("/some/other/path/track.m4a")
    assert _to_container_path(filepath, None) == "/audio/track.m4a"


def test_to_container_path_fallback_not_relative() -> None:
    filepath = Path("/other/path/track.m4a")
    output_dir = Path("/Users/me/Music/DJ Library")
    assert _to_container_path(filepath, output_dir) == "/audio/track.m4a"


async def test_analyze_success() -> None:
    mock_response = httpx.Response(200, json=SAMPLE_ANALYSIS_JSON)
    with patch("server.analyzer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(
            Path("/Users/me/Music/DJ Library/track.m4a"),
            output_dir=Path("/Users/me/Music/DJ Library"),
        )

    assert result is not None
    assert result.bpm == 128.0
    assert result.key == "Am"
    assert len(result.segments) == 1


async def test_analyze_container_unreachable() -> None:
    with patch("server.analyzer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(Path("/path/to/track.m4a"))

    assert result is None


async def test_analyze_container_error_response() -> None:
    error_json = {"status": "error", "message": "Analysis failed"}
    mock_response = httpx.Response(200, json=error_json)
    with patch("server.analyzer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(Path("/path/to/track.m4a"))

    assert result is None


async def test_analyze_writes_vdj_on_success(tmp_path: Path) -> None:
    mock_response = httpx.Response(200, json=SAMPLE_ANALYSIS_JSON)
    with (
        patch("server.analyzer.httpx.AsyncClient") as mock_client_cls,
        patch("server.analyzer.write_to_vdj_database") as mock_vdj,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(
            Path("/Users/me/Music/DJ Library/track.m4a"),
            vdj_db_path=tmp_path / "database.xml",
            output_dir=Path("/Users/me/Music/DJ Library"),
        )

    assert result is not None
    mock_vdj.assert_called_once()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_analyzer.py -v`

Expected: All tests pass.

---

## Task 5: Add analyzer_url to config and update /api/analyze endpoint

**Goal:** Make the analyzer URL configurable and pass `output_dir` to `analyze_audio` for filepath translation.

**Files:**
- Modify: `server/config.py` (add `analyzer_url` field to `AnalysisConfig`)
- Modify: `server/app.py` (pass `analyzer_url` and `output_dir` to `analyze_audio`)
- Modify: `tests/test_app.py` (update analyze tests)

**Step 1: Add analyzer_url to AnalysisConfig**

In `server/config.py`, add the field to `AnalysisConfig`:

```python
class AnalysisConfig(BaseModel):
    enabled: bool = True
    vdj_database: Path = Path("~/Documents/VirtualDJ/database.xml").expanduser()
    max_cues: int = 8
    analyzer_url: str = "http://localhost:9235"
```

**Step 2: Update /api/analyze endpoint in server/app.py**

Pass the new config fields to `analyze_audio`:

```python
@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    filepath = Path(req.filepath)
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "file_not_found", "message": f"File not found: {req.filepath}"},
        )

    cfg = load_config()
    vdj_path = cfg.analysis.vdj_database if cfg.analysis.enabled else None
    result = await analyze_audio(
        filepath,
        vdj_db_path=vdj_path,
        max_cues=cfg.analysis.max_cues,
        analyzer_url=cfg.analysis.analyzer_url,
        output_dir=cfg.output_dir,
    )

    if result is None:
        raise HTTPException(
            status_code=500,
            detail={"error": "analysis_failed", "message": "Audio analysis failed"},
        )

    return AnalyzeResponse(status="ok", analysis=result)
```

**Step 3: Run all tests**

Run: `uv run pytest -v`

Expected: All tests pass.

---

## Task 6: Clean up main server dependencies

**Goal:** Remove ML-only dependencies from the main server's pyproject.toml since they now live in the Docker container. Keep httpx (new) and remove allin1, essentia, madmom, soundfile (container-only).

**Files:**
- Modify: `pyproject.toml`
- Delete: `server/key_detect.py` (moved to container)
- Delete: `server/beat_utils.py` (moved to container)
- Delete: `server/edm_reclassify.py` (moved to container)
- Delete: `tests/test_key_detect.py` (tests live conceptually with the container now)
- Delete: `tests/test_beat_utils.py`
- Delete: `tests/test_edm_reclassify.py`
- Modify: `server/models.py` (remove SegmentInfo/AnalysisResult if unused — check first)

**Step 1: Update pyproject.toml dependencies**

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
]
```

Remove `numpy`, `soundfile`, `essentia`, `madmom`, `allin1` from dependencies.

Remove the `[tool.uv.sources]` entries for `madmom` and `allin1`.

Remove the `[tool.uv.extra-build-dependencies]` section.

Remove `mypy.overrides` for `allin1`, `essentia`, `demucs`, `madmom`, `natten`, `soundfile`.

**Step 2: Check if SegmentInfo/AnalysisResult are still used by main server**

`server/models.py` — `SegmentInfo` and `AnalysisResult` are still used by:
- `server/app.py` (AnalyzeResponse references AnalysisResult)
- `server/vdj.py` (references SegmentInfo and AnalysisResult)
- `server/analyzer.py` (returns AnalysisResult)
- `tests/test_app.py` and `tests/test_models.py`

Keep them in `server/models.py`. They're Pydantic models used for the API contract.

**Step 3: Delete container-only modules from server/**

Delete: `server/key_detect.py`, `server/beat_utils.py`, `server/edm_reclassify.py`

Delete: `tests/test_key_detect.py`, `tests/test_beat_utils.py`, `tests/test_edm_reclassify.py`

**Step 4: Run uv sync and tests**

Run: `uv sync && uv run pytest -v`

Expected: All remaining tests pass. No import errors.

**Step 5: Run type check**

Run: `uv run mypy server/`

Expected: No errors.

---

## Task 7: Update README and docs

**Goal:** Update README with Docker Compose instructions, update ARCHITECTURE.md and PLANS.md.

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PLANS.md`

**Step 1: Update README.md**

Add Docker setup section and update the workflow:

In the Prerequisites section, add:
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (required for audio analysis)

In the Setup > Server section, replace the content with:

```markdown
### Server

```bash
# Install Python dependencies
uv sync

# Build and start the analyzer container (required for audio analysis)
docker compose up -d

# Run the server on port 9234
uv run uvicorn server.app:app --reload --port 9234
```

> **Note:** The analyzer container runs ML-based audio analysis (song structure, BPM, key detection) in a Linux environment. This is required because some ML libraries (NATTEN) don't have macOS ARM64 support. The main server handles downloading, tagging, and LLM enrichment natively.
```

Update the Usage section:

```markdown
1. Start the analyzer: `docker compose up -d`
2. Start the server: `uv run uvicorn server.app:app --reload --port 9234`
```

Update the Development table to include:
| Start analyzer | `docker compose up -d` |
| Rebuild analyzer | `docker compose build --no-cache` |
| Analyzer logs | `docker compose logs -f analyzer` |

**Step 2: Update docs/ARCHITECTURE.md**

Add the analyzer container to the Code Map table and update the Data Flow section to mention the HTTP call.

**Step 3: Update docs/PLANS.md**

Move the Docker tech debt item to a new completed plan entry. Update Current State.

---

## Task 8: Integration test — end-to-end verify

**Goal:** Verify the full flow works: Docker container builds, starts, main server can call it, and a real (or mocked) analysis round-trip works.

**Steps:**

1. `docker compose build` — verify image builds
2. `docker compose up -d` — verify container starts
3. `curl http://localhost:9235/health` — verify `{"status":"ok"}`
4. `uv run pytest -v` — verify all tests pass
5. `uv run mypy server/` — verify type checks pass
6. `uv run ruff check . && uv run ruff format --check .` — verify lint/format
7. `docker compose down` — clean up

---

## Outcomes & Retrospective

**What worked:**
- Parallel dispatch of independent tasks (1, 2, 3) cut wall-clock time significantly
- Clean separation: container owns ML pipeline, main server owns HTTP client + VDJ write
- 63 ML packages removed from main server — much lighter dependency footprint
- Zero plan drift — all 8 tasks implemented as designed

**What didn't:**
- Parallel workers can commit each other's files (worker 1 committed worker 2's untracked files) — minor but could cause confusion

**Learnings to codify:**
- When dispatching parallel workers that create files in the same directory, consider using worktree isolation or explicit `git add` of only their own files
- The brainstorming phase correctly identified the split architecture (analysis-only container vs whole server) — user preference for Claude CLI drove the right design
- Platform compatibility (NATTEN macOS ARM64) should be validated during brainstorming, not discovered during implementation
