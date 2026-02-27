# Audio Post-Processing Design

ML-based audio analysis pipeline for automatic song structure detection, BPM/key analysis, bar counting, and Virtual DJ cue point generation.

## Problem

After downloading a track, a DJ needs to know its structure (where the drops, buildups, breakdowns are), BPM, key, and how many bars each section lasts — before they can mix it. Currently this requires manual listening or commercial tools like Mixed In Key. We want to automate this as a post-download step.

## Approach

**allin1 + essentia + custom EDM reclassifier**, writing results to VDJ's `database.xml`.

- **allin1** — single-pass ML analysis returning song structure segments (intro, verse, chorus, break, etc.), BPM, beat positions, and downbeats. Uses Demucs source separation + Neighborhood Attention Transformer. State-of-the-art accuracy on EDM-adjacent music (ISMIR 2023).
- **essentia** — EDM-tuned key detection via `KeyExtractor(profileType='bgate')`, trained on BeatPort corpus.
- **Custom EDM reclassifier** — transforms allin1's pop-oriented labels into DJ terminology (Drop, Buildup, Breakdown) using per-stem energy analysis from Demucs's intermediate output.

### Why not alternatives?

| Option | Why not |
|--------|---------|
| essentia alone | No structure segmentation capability at all |
| MSAF | Classical algorithms, no semantic labels, not competitive with ML |
| Rekordbox phrase analysis | Requires Rekordbox installed and tracks pre-analyzed |
| Full custom (Demucs + energy from scratch) | Reimplements years of MIR research; lower accuracy than allin1 |

## Architecture

### New module: `server/analyzer.py`

Sits alongside `downloader.py`, `tagger.py`, `enrichment.py`. Single async entry point: `analyze_audio(filepath) -> AnalysisResult`.

### Trigger

Post-download hook. After `download_audio()` + `tag_file()` complete, the download endpoint fires `analyze_audio()` as a background task. The download response returns immediately. The extension polls or receives a callback when analysis finishes.

### Data output

Analysis results written to VDJ's `database.xml` (sidecar XML, not embedded tags). This is a separate concern from ID3/Vorbis tagging in `tagger.py`.

## Analysis Pipeline

Five stages, run sequentially on the downloaded audio file:

### Stage 1: Structure Analysis (allin1)

```python
result = allin1.analyze(filepath)
# result.bpm: float (e.g., 128.0)
# result.beats: list[float] (beat positions in seconds)
# result.downbeats: list[float] (downbeat positions)
# result.segments: list[Segment] (start, end, label)
```

Labels: `intro`, `outro`, `verse`, `chorus`, `bridge`, `break`, `inst`, `solo`, `start`, `end`.

Heavy pass (~30-60s). Demucs runs internally, separating into 4 stems (drums, bass, other, vocals).

### Stage 2: Key Detection (essentia)

```python
key_extractor = essentia.standard.KeyExtractor(profileType='bgate')
key, scale, strength = key_extractor(audio)
# e.g., ("A", "minor", 0.87) -> "Am", Camelot "8A"
```

Fast (~1-2s). `bgate` profile calibrated on BeatPort EDM corpus.

### Stage 3: EDM Reclassification

Transform allin1's pop labels into EDM terminology using per-stem RMS energy:

| allin1 label | Energy signature | EDM label |
|---|---|---|
| `chorus` | High drums + high bass RMS | **Drop** |
| `chorus` | Lower energy (no kick dominance) | **Chorus** |
| `break` | Low energy, before a drop | **Breakdown** |
| `break` | Rising onset density | **Buildup** |
| `verse` | Moderate energy | **Verse** |
| `bridge` | — | **Bridge** |
| `intro` | — | **Intro** |
| `outro` | — | **Outro** |
| `inst` / `solo` | — | **Instrumental** / **Solo** |

Energy data extracted from Demucs stems (computed in Stage 1). Per segment: compute mean RMS of drums stem and bass stem over the segment's time range.

### Stage 4: Bar Counting

Count downbeats within each segment's `[start, end)` range. In 4/4 time (verified from allin1's `beat_positions` cycling 1-4), each downbeat = one bar boundary.

### Stage 5: Beat-Snapping

Snap each segment boundary to the nearest downbeat. Ensures all cue points land exactly on the beat grid — critical for DJ use. Find the downbeat with minimum absolute distance to each boundary timestamp.

## VDJ Integration

### Target

`~/Documents/VirtualDJ/database.xml` (macOS default, configurable).

### What we write per track

1. **`<Scan>`** — BPM as seconds-per-beat (`60.0 / bpm`), Key (e.g., "Am")
2. **`<Poi Type="beatgrid">`** — First downbeat position as beatgrid anchor
3. **Named hot cues** — Up to 8 `<Poi>` elements, prioritized by DJ importance:
   - Priority: Drop > Buildup > Breakdown > Intro > Outro > Verse > Bridge > Instrumental/Solo
   - Name format: `"Drop 1 (16 bars)"`, `"Buildup (8 bars)"`, `"Intro (32 bars)"`
   - Position: beat-snapped segment start time (seconds)

### XML format

```xml
<Song FilePath="/path/to/track.m4a">
  <Scan Bpm="0.46875" Key="Am" Version="801" />
  <Poi Pos="0.234" Type="beatgrid" />
  <Poi Name="Intro (32 bars)" Pos="0.234" Num="1" />
  <Poi Name="Buildup (8 bars)" Pos="60.5" Num="2" />
  <Poi Name="Drop 1 (16 bars)" Pos="75.3" Num="3" />
  <Poi Name="Breakdown (8 bars)" Pos="105.7" Num="4" />
  <Poi Name="Buildup (8 bars)" Pos="120.1" Num="5" />
  <Poi Name="Drop 2 (16 bars)" Pos="135.5" Num="6" />
  <Poi Name="Outro (16 bars)" Pos="165.9" Num="7" />
</Song>
```

### Safety

- Read-modify-write with file locking (VDJ may have the file open)
- Back up database before first write
- Auto-generated cues use a naming convention to distinguish from manual cues
- If VDJ not installed (no `database.xml`), skip silently with warning log

## Models

```python
class SegmentInfo(BaseModel):
    label: str            # EDM label: "Drop", "Buildup", "Breakdown", etc.
    original_label: str   # allin1 raw label: "chorus", "break", etc.
    start: float          # beat-snapped start time (seconds)
    end: float            # beat-snapped end time (seconds)
    bars: int             # number of bars in this section

class AnalysisResult(BaseModel):
    bpm: float
    key: str              # e.g., "Am"
    key_camelot: str      # e.g., "8A"
    beats: list[float]
    downbeats: list[float]
    segments: list[SegmentInfo]
    vdj_written: bool     # whether database.xml was updated
```

## API

### Updated endpoint: `POST /api/download`

Existing behavior unchanged. After download + tagging, fires `analyze_audio()` as background task. Response includes `analysis: AnalysisResult | None` (None initially, populated when analysis completes).

### New endpoint: `POST /api/analyze`

Accepts `{ filepath: str }`. Runs full analysis pipeline. Returns `AnalysisResult`. For re-analyzing or analyzing existing files.

## Extension Updates

- Show analysis status per queue item: "Analyzing...", "Analyzed", or "Analysis failed"
- Display detected structure, BPM, key on completed items (read-only)
- No editing of analysis results from the extension

## Dependencies

Added to project's `uv` environment:

- `allin1` — structure analysis (pulls in PyTorch, Demucs, NATTEN, madmom)
- `essentia` — key detection (pre-built macOS ARM64 wheels)
- `torch` / `torchaudio` — ML runtime (required by allin1)

Total additional footprint: ~2-3 GB.

## Error Handling

- **allin1 failure**: Log error, skip analysis. Download still succeeds. Return `analysis: None`.
- **Short tracks (<30s)**: Run analysis but expect unreliable results. No special handling.
- **Variable BPM**: Beat positions reflect tempo variations. Bar counting uses actual beat positions, not constant BPM.
- **VDJ not installed**: Skip VDJ write, log warning. Still return AnalysisResult.
- **Demucs stem access**: Extract stem energy during allin1's call before cleanup, or run a lightweight separate Demucs pass for the reclassifier.

## Open Questions

1. **Demucs stem access from allin1**: Does allin1's API expose intermediate Demucs stems, or do we need a separate Demucs pass for the EDM reclassifier? Needs investigation during implementation.
2. **NATTEN macOS compatibility**: NATTEN + PyTorch version pinning may be fragile on macOS ARM64. Need to verify during setup.
3. **Analysis notification**: Should the extension poll for analysis completion, or should the server push a notification? Current architecture (HTTP request/response) suggests polling.
