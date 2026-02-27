# Architecture

This document describes the high-level architecture of dj-kompanion.
If you want to familiarize yourself with the codebase, you are in the right place.

## Bird's Eye View

dj-kompanion is a personal convenience tool that wraps the yt-dlp CLI utility with a Chrome extension frontend and a local backend server. The user clicks a button in Chrome, the extension sends the current page URL to a local service, which runs yt-dlp to download audio/video and extract metadata. The metadata is then formatted for DJ software (e.g., Virtual DJ) and optionally enriched by an LLM agent for tasks like sanitizing tags or marking song structure (intro, buildup, drop).

Input: a URL from the browser. Output: a downloaded media file with DJ-ready metadata.

## Code Map

| Module | Purpose |
|--------|---------|
| `server/app.py` | FastAPI endpoints: health, preview, download |
| `server/models.py` | Pydantic models shared between endpoints |
| `server/enrichment.py` | LLM enrichment (basic_enrich, enrich_metadata, try_enrich_metadata, merge_metadata) |
| `server/downloader.py` | yt-dlp wrapper for metadata extraction and audio download |
| `server/tagger.py` | File tagging via mutagen, filename sanitization |
| `server/config.py` | Configuration loading |
| `extension/src/popup.ts` | Chrome extension popup UI and state management |
| `extension/src/api.ts` | HTTP client for server communication |
| `extension/src/types.ts` | TypeScript interfaces mirroring Pydantic models |

## Data Flow

1. **Preview**: Extension sends URL -> server extracts metadata via yt-dlp -> basic_enrich parses artist/title -> returns raw + enriched to extension
2. **Download**: Extension sends URL + metadata + raw + user_edited_fields -> server runs yt-dlp download + Claude enrichment in parallel -> merge_metadata combines results respecting user edits -> tag_file writes metadata to downloaded file

## Cross-Cutting Concerns

| Concern | Pattern |
|---------|---------|
| Enrichment fallback | Claude failure -> basic_enrich fallback -> user metadata as last resort |
| User edit priority | Extension tracks initialMetadata snapshot; merge_metadata preserves user-edited fields |
| Error boundaries | Each endpoint catches domain exceptions (DownloadError, TaggingError) and returns structured JSON errors |
