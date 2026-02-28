# Architecture

This document describes the high-level architecture of dj-kompanion.
If you want to familiarize yourself with the codebase, you are in the right place.

## Bird's Eye View

dj-kompanion is a personal convenience tool that wraps the yt-dlp CLI utility with a Chrome extension frontend and a local backend server. The user clicks a button in Chrome, the extension sends the current page URL to a local service, which runs yt-dlp to download audio/video and extract metadata. The metadata is then formatted for DJ software (e.g., Virtual DJ) and optionally enriched by an LLM agent for tasks like sanitizing tags or marking song structure (intro, buildup, drop).

Input: a URL from the browser. Output: a downloaded media file with DJ-ready metadata and VDJ cue points.

## Code Map

| Module | Purpose |
|--------|---------|
| `server/app.py` | FastAPI endpoints: health, preview, download, retag, analyze |
| `server/models.py` | Pydantic models shared between endpoints (including SegmentInfo, AnalysisResult) |
| `server/enrichment.py` | LLM enrichment (basic_enrich, enrich_metadata, try_enrich_metadata, merge_metadata) |
| `server/downloader.py` | yt-dlp wrapper for metadata extraction and audio download |
| `server/tagger.py` | File tagging via mutagen, filename sanitization |
| `server/config.py` | Configuration loading (AppConfig, LLMConfig, AnalysisConfig) |
| `server/analyzer.py` | HTTP client proxying analysis requests to the analyzer container |
| `server/vdj.py` | Virtual DJ database.xml writer with priority-based cue points |
| `analyzer/app.py` | Analyzer container: FastAPI with POST /analyze endpoint |
| `analyzer/pipeline.py` | Analyzer container: 5-stage analysis pipeline orchestrator |
| `analyzer/key_detect.py` | Analyzer container: essentia key detection + Camelot notation |
| `analyzer/beat_utils.py` | Analyzer container: beat-snapping and bar-counting |
| `analyzer/edm_reclassify.py` | Analyzer container: EDM label reclassifier using stem energy |
| `analyzer/models.py` | Analyzer container: Pydantic models (AnalysisResult, SegmentInfo, request/response) |
| `extension/src/popup.ts` | Chrome extension popup: queue list renderer, inline preview/edit, retag, analysis display |
| `extension/src/background.ts` | Service worker: queue download processing loop, post-download analysis trigger, badge, stale recovery |
| `extension/src/api.ts` | HTTP client for server communication (health, preview, download, retag, analyze) |
| `extension/src/types.ts` | TypeScript interfaces mirroring Pydantic models + QueueItem + analysis types |

## Data Flow

1. **Preview**: Extension sends URL -> server extracts metadata via yt-dlp -> basic_enrich parses artist/title -> returns raw + enriched to extension
2. **Queue**: User confirms metadata in popup -> QueueItem written to chrome.storage.local -> service worker picks up pending items sequentially
3. **Download**: Service worker sends URL + metadata + raw + user_edited_fields -> server runs yt-dlp download + Claude enrichment in parallel -> merge_metadata combines results respecting user edits -> tag_file writes metadata -> response includes final metadata + enrichment source
4. **Analysis** (post-download): Extension calls POST /api/analyze → main server translates filepath to container mount path → calls analyzer container (Docker, port 9235) over HTTP → container runs 5-stage ML pipeline (allin1 structure, essentia key, EDM reclassify, bar count, beat-snap) → returns AnalysisResult JSON → main server writes results to VDJ database.xml as named hot cues. Extension updates item status.
5. **On-demand analysis**: Extension or user calls POST /api/analyze with filepath -> same pipeline as above -> returns AnalysisResult
6. **Retag**: User edits tags on completed item -> extension sends filepath + metadata to /api/retag -> server re-writes tags via tag_file (may rename file)

## Logging

Server logs to `~/.config/dj-kompanion/logs/server.log` via `server/logging_config.py`.

- Rotating file handler: 500 KB max, 2 backups (1.5 MB total cap)
- File handler captures DEBUG level (includes raw Claude CLI stdout/stderr)
- Console handler at INFO level
- `setup_logging()` called at module level in `server/app.py`
- Enrichment module logs: raw Claude stdout at DEBUG, parse failures at WARNING

## Cross-Cutting Concerns

| Concern | Pattern |
|---------|---------|
| Enrichment fallback | Claude failure -> basic_enrich fallback -> user metadata as last resort |
| User edit priority | Extension tracks initialMetadata snapshot; merge_metadata preserves user-edited fields |
| Error boundaries | Each endpoint catches domain exceptions (DownloadError, TaggingError) and returns structured JSON errors |
| Queue persistence | chrome.storage.local is single source of truth; popup is stateless renderer; service worker owns download lifecycle |
| Stale recovery | Service worker resets "downloading" to "pending" and "analyzing" to "complete" on startup |
| Analysis fallback | Analyzer container unreachable → analyze returns None; individual pipeline stages fail gracefully with partial results |
| VDJ cue priority | Drop > Buildup > Breakdown > Intro > Outro > Verse > Bridge > Inst/Solo; max 8 cue slots |
