# Architecture

This document describes the high-level architecture of dj-kompanion.
If you want to familiarize yourself with the codebase, you are in the right place.

## Bird's Eye View

dj-kompanion is a personal convenience tool that wraps the yt-dlp CLI utility with a Chrome extension frontend and a local backend server. The user clicks a button in Chrome, the extension sends the current page URL to a local service, which runs yt-dlp to download audio/video and extract metadata. The metadata is then formatted for DJ software (e.g., Virtual DJ) and optionally enriched by an LLM agent for tasks like sanitizing tags or marking song structure (intro, buildup, drop).

Input: a URL from the browser. Output: a downloaded media file with DJ-ready metadata and VDJ cue points.

## Code Map

| Module | Purpose |
|--------|---------|
| `server/app.py` | FastAPI endpoints: health, download, retag, sync-vdj, tracks, reanalyze |
| `server/models.py` | Pydantic models shared between endpoints (including SegmentInfo, AnalysisResult) |
| `server/enrichment.py` | LLM enrichment with API candidate selection (basic_enrich, enrich_metadata, try_enrich_metadata, merge_metadata) |
| `server/downloader.py` | yt-dlp wrapper for metadata extraction and audio download |
| `server/tagger.py` | File tagging via mutagen, filename sanitization |
| `server/config.py` | Configuration loading (AppConfig, LLMConfig, AnalysisConfig, MetadataLookupConfig) |
| `server/metadata_lookup.py` | MusicBrainz + Last.fm search: MetadataCandidate, search_musicbrainz, search_lastfm, search_metadata |
| `server/analyzer.py` | HTTP client proxying analysis requests to the analyzer container; writes sidecar + SQLite |
| `server/track_db.py` | SQLite track status database: downloaded → analyzing → analyzed → synced |
| `server/analysis_store.py` | Read/write analysis results as sidecar `.meta.json` files |
| `server/vdj.py` | Virtual DJ database.xml writer with priority-based cue points |
| `server/vdj_sync.py` | Batch sync analysis results to VDJ database.xml with safety checks |
| `analyzer/app.py` | Analyzer container: FastAPI with POST /analyze endpoint |
| `analyzer/pipeline.py` | Analyzer container: 5-stage analysis pipeline orchestrator |
| `analyzer/key_detect.py` | Analyzer container: essentia key detection + Camelot notation |
| `analyzer/beat_utils.py` | Analyzer container: beat-snapping and bar-counting |
| `analyzer/edm_reclassify.py` | Analyzer container: EDM label reclassifier using stem energy |
| `analyzer/models.py` | Analyzer container: Pydantic models (AnalysisResult, SegmentInfo, request/response) |
| `extension/src/popup.ts` | Chrome extension popup: queue list renderer, inline edit, retag, sync-to-VDJ button |
| `extension/src/background.ts` | Service worker: queue download processing loop, badge, stale recovery |
| `extension/src/api.ts` | HTTP client for server communication (health, download, retag, sync-vdj, tracks, reanalyze) |
| `extension/src/types.ts` | TypeScript interfaces mirroring Pydantic models + QueueItem + analysis types |

## Data Flow

1. **Preview**: Extension sends URL -> server extracts metadata via yt-dlp -> basic_enrich parses artist/title -> returns raw + enriched to extension
2. **Queue**: User confirms metadata in popup -> QueueItem written to chrome.storage.local -> service worker picks up pending items sequentially
3. **Download**: Service worker sends URL + metadata + raw + user_edited_fields -> server runs yt-dlp download + API metadata search (MusicBrainz + Last.fm) in parallel -> Claude receives raw metadata + API candidates, selects best match -> merge_metadata combines results respecting user edits -> tag_file writes metadata -> response includes final metadata + enrichment source (api+claude, claude, basic, or none)
4. **Analysis** (fire-and-forget): After download+tag, server inserts track into SQLite (`downloaded`), fires `asyncio.create_task` to call analyzer container → container runs 5-stage ML pipeline → server writes `.meta.json` sidecar to `~/.config/dj-kompanion/analysis/` and updates SQLite to `analyzed`. Download response returns immediately.
5. **VDJ Sync** (manual): User clicks "Sync to VDJ" in extension (or POST /api/sync-vdj) → server checks VDJ is not running → reads all `analyzed` tracks from SQLite → loads each `.meta.json` → writes cue POIs to VDJ database.xml → marks as `synced` in SQLite.
6. **Reanalyze**: POST /api/reanalyze resets track to `downloaded` and re-queues analysis.
7. **Retag**: User edits tags on completed item -> extension sends filepath + metadata to /api/retag -> server re-writes tags via tag_file (may rename file)

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
| Enrichment fallback | API+Claude -> Claude-only -> basic_enrich -> user metadata as last resort |
| Metadata API search | MusicBrainz + Last.fm searched in parallel at download time; candidates passed to Claude for disambiguation |
| User edit priority | Extension tracks initialMetadata snapshot; merge_metadata preserves user-edited fields |
| Error boundaries | Each endpoint catches domain exceptions (DownloadError, TaggingError) and returns structured JSON errors |
| Queue persistence | chrome.storage.local is single source of truth; popup is stateless renderer; service worker owns download lifecycle |
| Stale recovery | Service worker resets "downloading" to "pending" on startup |
| Analysis fallback | Analyzer container unreachable → marks track as `failed` in SQLite; individual pipeline stages fail gracefully |
| VDJ cue priority | Drop > Buildup > Breakdown > Intro > Outro > Verse > Bridge > Inst/Solo; max 8 cue slots |
| VDJ safety | Sync refuses to write if VDJ process is running; only modifies songs VDJ has already scanned |
| Analysis storage | Sidecar `.meta.json` in `~/.config/dj-kompanion/analysis/`; SQLite `tracks.db` for status tracking |
