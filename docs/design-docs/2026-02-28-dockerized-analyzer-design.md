# Dockerized Analyzer Microservice Design

Split the allin1 audio analysis pipeline into a separate Docker container so it works on macOS ARM64 (where NATTEN has no native wheels). The main server stays native for download/tag/enrich with Claude CLI access.

## Problem

allin1 depends on NATTEN, which only ships CUDA wheels (no macOS ARM64 support). The current code has a `try: import allin1` fallback that silently disables the entire analysis pipeline on Apple Silicon. Docker provides a Linux environment where NATTEN works.

## Architecture

Two local processes:

1. **Main server** (native, `uv run uvicorn`) — download, tag, enrich, VDJ write. Calls the analyzer over HTTP.
2. **Analyzer service** (Docker container) — minimal FastAPI app running the allin1 5-stage pipeline. Returns `AnalysisResult` JSON.

```
Chrome Extension
      │
      ▼
Main Server (native, port 9234)
  ├── /api/preview     — yt-dlp metadata extraction
  ├── /api/download    — yt-dlp + tag + Claude enrich
  ├── /api/retag       — re-tag existing file
  └── /api/analyze     ──HTTP──▶  Analyzer Container (Docker, port 9235)
        │                              ├── allin1 structure analysis
        │                              ├── essentia key detection
        │                              ├── EDM reclassification
        │                              ├── bar counting
        │                              └── beat-snapping
        ▼
  VDJ database.xml write (main server)
```

## Analyzer Container

- **Base image**: Python 3.11 slim on Linux
- **Dependencies**: allin1, essentia, madmom, numpy, soundfile, FastAPI, uvicorn
- **Single endpoint**: `POST /analyze` — accepts `{"filepath": "/audio/..."}`, returns `AnalysisResult`
- **Volume mount**: `~/Music/DJ Library` → `/audio` (read-only)
- **Port**: 9235

The container contains the analysis pipeline code: `analyzer.py` orchestrator, `key_detect.py`, `beat_utils.py`, `edm_reclassify.py`, and the analysis models from `models.py`.

## Main Server Changes

- `server/analyzer.py` refactored from direct allin1 import to HTTP client calling `http://localhost:{port}/analyze`
- Filepath translation: converts host path (`~/Music/DJ Library/file.m4a`) to container path (`/audio/file.m4a`) using the configured output_dir as the mount root
- VDJ write remains in the main server after receiving `AnalysisResult` from the container
- `server/config.py` gets `analysis.analyzer_url` (default `http://localhost:9235`)
- Graceful fallback: if analyzer service is unreachable, analysis returns None (same behavior as today's NATTEN fallback)

## File Structure

```
analyzer/
  Dockerfile
  app.py              # FastAPI with POST /analyze
  analyzer.py         # 5-stage pipeline (moved from server/analyzer.py)
  key_detect.py       # essentia key detection
  beat_utils.py       # bar counting + beat-snapping
  edm_reclassify.py   # EDM label reclassification
  models.py           # AnalysisResult, SegmentInfo (subset of server/models.py)
  requirements.txt
docker-compose.yml    # Analyzer service only
```

## docker-compose.yml

```yaml
services:
  analyzer:
    build: ./analyzer
    ports:
      - "9235:9235"
    volumes:
      - ~/Music/DJ Library:/audio:ro
```

## API Contract

### POST /analyze

Request:
```json
{"filepath": "/audio/Artist - Title.m4a"}
```

Response (success):
```json
{
  "status": "ok",
  "analysis": {
    "bpm": 128.0,
    "key": "Am",
    "key_camelot": "8A",
    "beats": [0.5, 0.97, ...],
    "downbeats": [0.5, 2.4, ...],
    "segments": [
      {
        "label": "Intro",
        "original_label": "intro",
        "start": 0.5,
        "end": 30.2,
        "bars": 16
      }
    ]
  }
}
```

Response (failure):
```json
{"status": "error", "message": "Analysis failed: ..."}
```

## Workflow

```bash
docker compose up -d                                    # Start analyzer
uv run uvicorn server.app:app --reload --port 9234      # Start main server
```

## Error Handling

- Analyzer container unreachable → analysis returns None, download still succeeds
- allin1 fails inside container → returns error JSON, main server logs and returns None
- Individual stages (key, reclassify) fail → container catches per-stage, returns partial results where possible

## Decisions

| Decision | Rationale |
|----------|-----------|
| Separate container for analysis only | Keeps Claude CLI working natively; analysis is the only part that needs Linux |
| Volume mount over file upload | Audio files already on disk; no upload overhead for 5-20MB files |
| Main server owns VDJ write | Container stays read-only; clean separation of concerns |
| Configurable analyzer URL | Allows pointing to remote analyzer or different port |
| Copy analysis code into container | Self-contained; no shared imports between native server and container |
