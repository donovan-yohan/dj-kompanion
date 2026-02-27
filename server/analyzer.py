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

try:
    import allin1
except ImportError:
    allin1 = None

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
    import shutil
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
        shutil.rmtree(demix_dir, ignore_errors=True)
    except Exception:
        pass

    logger.info(
        "Analysis complete for %s: BPM=%.1f, Key=%s, %d segments",
        filepath, bpm, key, len(segments),
    )
    return result
