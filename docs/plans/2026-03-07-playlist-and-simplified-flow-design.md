# Playlist Support & Simplified Download Flow

**Date:** 2026-03-07
**Status:** Approved

## Problem

1. The preview step (fetch metadata → edit → queue) adds friction to the download flow.
2. YouTube playlist URLs cause yt-dlp to resolve the entire playlist instead of the current video.
3. No way to download all tracks from a playlist.

## Design

### Extension UI

Replace the multi-step preview flow with a single-screen action bar:

- **Format dropdown** (`m4a | mp3 | flac | ogg`): Persisted in `chrome.storage.sync`, defaults to `m4a`.
- **Download button**: Always visible when connected. Strips `list`/`index` params, creates a single queue item immediately.
- **Download Playlist button**: Only visible when URL contains `list=`. Calls `/api/resolve-playlist`, creates one queue item per track.
- **Preview step removed**: No fetch → loading → preview → queue flow. Just action bar + queue list.
- Queue list unchanged — completed items expand for metadata editing, retag, analysis results.

### Server: New Endpoint

```
POST /api/resolve-playlist
Request:  { url: string, cookies?: CookieData[] }
Response: { tracks: [{ url: string, title: string }], playlist_title: string }
```

- Uses yt-dlp `extract_flat: "in_playlist"` for fast resolution (URLs + titles only).
- `noplaylist` is NOT set on this endpoint.
- Existing `/api/download` unchanged — each track goes through download → enrich → tag as before.

### Queue & Background Worker

- Playlist items are standard `QueueItem`s — no new types.
- "Download Playlist" creates all items at once with placeholder metadata (YouTube title, empty artist).
- "Download" (single video) creates one item using `tabs[0].title` as placeholder.
- `QueueItem.raw` becomes nullable (no preview to populate it upfront).
- Background worker unchanged — processes pending items sequentially, enrichment fills metadata during download.

### What Stays the Same

- `/api/download` endpoint and download → enrich → tag pipeline
- Sequential queue processing in background worker
- Expandable metadata editing on completed queue items
- Analysis flow
- Retag flow
