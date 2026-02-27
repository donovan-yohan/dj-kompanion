# Download Queue — Design

**Date:** 2026-02-26
**Status:** Approved
**Depends On:** Phase 4 (Chrome Extension) — extends existing popup UI

## Context

The current extension popup handles one download at a time: fetch metadata, edit, download, wait, see result. The popup must stay open the entire time. Users want to queue multiple downloads and navigate away while they process.

## Goal

Transform the popup into a queue-based UI where:
- Opening the popup shows recent downloads and their statuses
- "Fetch from Current URL" previews metadata inline, "Download" adds to the queue
- The service worker processes downloads in the background (popup can close)
- Queue state persists in `chrome.storage.local` across popup close/open and browser restarts
- Failed items show a manual retry button (with the original URL preserved)
- Completed items show enrichment status and allow inline tag editing with a retag endpoint

## Popup Layout

```
┌──────────────────────────────────┐
│  dj-kompanion          ● Online  │
│──────────────────────────────────│
│                                  │
│  [Fetch from Current URL]        │
│                                  │
│── Recent Downloads ──────────────│
│  ◐ Downloading...                │
│  Ninajirachi - iPod Touch        │
│  ──────────────────────────────  │
│  ✓ ✨ DJ Snake - Turn Down ...   │
│  → ~/Music/DJ Library/file.m4a   │
│  ──────────────────────────────  │
│  ✗ Artist - Broken Song          │
│  Connection refused     [Retry]  │
│                                  │
│  (max 10 items, most recent top) │
└──────────────────────────────────┘
```

Clicking "Fetch from Current URL" expands an inline metadata edit form (same fields as today). Clicking "Download" collapses the form and adds the item to the queue list.

### Completed item detail (expanded)

Clicking a completed item expands it to show the full metadata and allows editing:

```
┌──────────────────────────────────┐
│  ✓ ✨ DJ Snake - Turn Down ...   │
│  → ~/Music/DJ Library/file.m4a   │
│  ──────────────────────────────  │
│  Artist: [DJ Snake          ]    │
│  Title:  [Turn Down for What]    │
│  Genre:  [Trap              ]    │
│  Year:   [2014              ]    │
│  ...                             │
│         [Save Tags]  [Cancel]    │
└──────────────────────────────────┘
```

The ✨ icon indicates Claude enrichment was applied. "Save Tags" calls `POST /api/retag` to re-write tags to the file on disk.

## Data Model

```typescript
interface QueueItem {
  id: string;                    // unique ID (timestamp + random suffix)
  url: string;                   // source URL (preserved for retry)
  metadata: EnrichedMetadata;    // user-confirmed metadata
  raw: RawMetadata;              // raw metadata from preview
  format: string;                // "m4a", "mp3", "flac", etc.
  userEditedFields: string[];    // fields user modified
  status: "pending" | "downloading" | "complete" | "error";
  enrichmentSource?: "claude" | "basic" | "none";  // set on complete
  filepath?: string;             // set on complete
  error?: string;                // set on error
  addedAt: number;               // Date.now() timestamp
}
```

Queue stored in `chrome.storage.local` under key `"queue"` as `QueueItem[]`.

## Architecture

### Popup (renderer)

The popup becomes a stateless renderer of queue state:

- **On open:** read queue from `chrome.storage.local`, render list + "Fetch from Current URL" button
- **Fetch metadata:** same as today — call `/api/preview`, show inline edit form
- **Download:** build `QueueItem` with status `"pending"`, write to storage, send `"queue_add"` message to service worker
- **Retry:** update item status to `"pending"`, send `"queue_process"` message to service worker
- **Live updates:** listen to `chrome.storage.onChanged` to re-render when the service worker updates item statuses

The popup no longer manages download lifecycle — it dispatches and observes.

### Service Worker (download processor)

The service worker owns the download lifecycle:

- **On `"queue_add"` / `"queue_process"` message:** start processing loop
- **Processing loop:** read queue from storage, find first `"pending"` item, set it to `"downloading"`, call `/api/download`, update to `"complete"` or `"error"`. On complete, store `enrichmentSource` and updated `metadata` from the server response
- **Sequential processing:** one download at a time to avoid overwhelming the server
- **Badge:** show count of pending + downloading items (e.g., "2"), clear when queue is idle
- **On service worker wake:** check for any `"downloading"` items (stale from a killed worker) and reset them to `"pending"` for automatic retry

### Storage as source of truth

`chrome.storage.local` is the single source of truth. Both popup and service worker read/write to it. The `chrome.storage.onChanged` event keeps the popup in sync without polling.

## Popup States

The popup simplifies from 6 states to 2 views:

1. **Queue view** (default): "Fetch from Current URL" button + scrollable queue list
2. **Preview view**: inline metadata edit form (replaces the button area temporarily)

Queue items render based on their own `status` field — no global popup state machine needed for download tracking.

## Queue Management

- **Cap:** 10 items displayed, most recent first
- **Cleanup:** completed/errored items older than the 10-item window are pruned on popup open
- **Retry:** sets item status back to `"pending"`, triggers service worker processing

## Server: Retag Endpoint

New endpoint to re-write tags on an existing file without re-downloading:

```
POST /api/retag
{
  "filepath": "/Users/.../Music/DJ Library/Artist - Title.m4a",
  "metadata": { ...EnrichedMetadata }
}
→ { "status": "ok", "filepath": "/Users/.../Artist - Title.m4a" }
```

Uses the existing `tag_file()` from `server/tagger.py`. The filepath may change if artist/title were edited (tagger renames the file).

## Server: Download Response Update

The existing `/api/download` response already includes `enrichment_source`. It needs to also return the final merged metadata so the extension can store and display the enriched values:

```
POST /api/download → { status, filepath, enrichment_source, metadata }
```

## What Changes

| Component | Change |
|-----------|--------|
| `popup.ts` | Rewrite: queue list renderer + inline preview form + expandable completed items |
| `popup.html` | Update: queue list section, remove single-download states |
| `popup.css` | Update: queue item styles, scrollable list, expandable detail view |
| `background.ts` | Expand: download processing loop, badge count |
| `types.ts` | Add: `QueueItem`, `RetagRequest`, `RetagResponse` interfaces |
| `api.ts` | Add: `requestRetag()` function |
| `server/app.py` | Add: `POST /api/retag` endpoint |
| `server/models.py` | Add: `RetagRequest`, `RetagResponse` models |

## What Stays the Same

- Existing server API endpoints (`/api/preview`, `/api/download`, `/api/health`) — unchanged except download response adds `metadata` field
- Metadata preview/edit form fields
- Options page (server host/port config)
- All server-side code (Python)
- TypeScript strict mode, build pipeline

## Error Handling

- **Server offline:** "Fetch from Current URL" disabled (same as today). Pending queue items stay pending until service worker can reach server.
- **Download fails:** item marked `"error"` with message, retry button shown
- **Service worker killed mid-download:** on next wake, stale `"downloading"` items reset to `"pending"`

## Success Criteria

- [ ] Popup shows queue list on open with recent download statuses
- [ ] "Fetch from Current URL" shows inline metadata preview/edit form
- [ ] "Download" adds item to queue and it appears in the list
- [ ] Downloads process in background after popup closes
- [ ] Queue persists across popup close/open
- [ ] Failed items show error message and retry button
- [ ] Retry re-queues the item using the stored URL
- [ ] Badge shows count of active downloads
- [ ] Queue capped at 10 items, most recent first
- [ ] Completed items with Claude enrichment show ✨ icon
- [ ] Clicking a completed item expands to show editable metadata
- [ ] "Save Tags" calls `/api/retag` and updates the file on disk
- [ ] `npm run typecheck` passes
- [ ] `npm run build` produces working dist/ output
- [ ] `/api/retag` endpoint works and re-writes tags to existing files
