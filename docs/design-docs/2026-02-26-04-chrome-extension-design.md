# Chrome Extension — Design

**Date:** 2026-02-26
**Status:** Approved
**Phase:** 4 (Frontend)
**Parent Design:** `2026-02-26-yt-dlp-dj-design.md`
**Depends On:** Phase 3 (Server) — needs working API endpoints

## Context

yt-dlp-dj is a Chrome extension + Python local server that wraps yt-dlp for one-click music downloading with DJ-ready metadata. This design doc covers the Chrome extension — the user-facing UI that captures the current page URL, previews metadata, allows editing, and triggers downloads.

## Goal

A working Chrome extension (Manifest V3) where:
- Clicking the extension icon opens a popup with the current tab URL
- "Fetch Metadata" calls the local server and displays enriched metadata
- User can edit any field before confirming
- "Download" triggers the server to download, tag, and save the file
- Clear feedback for server not running, errors, and success states

## Manifest V3

```json
{
  "manifest_version": 3,
  "name": "yt-dlp-dj",
  "version": "0.1.0",
  "description": "One-click music download with DJ-ready metadata",
  "permissions": ["activeTab"],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "background": {
    "service_worker": "dist/background.js"
  },
  "options_page": "options.html",
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

Only `activeTab` permission needed — we just read the current tab URL when the popup opens. No content scripts, no host permissions, no persistent background page.

## Popup States

### State 1: Initial

```
┌─────────────────────────────────┐
│  yt-dlp-dj                      │
│─────────────────────────────────│
│                                 │
│  ● Connected to local server    │
│                                 │
│  URL: https://youtu.be/abc123   │
│                                 │
│  [Fetch Metadata]               │
│                                 │
└─────────────────────────────────┘
```

On popup open:
1. Get current tab URL via `chrome.tabs.query({ active: true, currentWindow: true })`
2. Health check: `GET http://localhost:PORT/api/health`
3. Show connection status (green dot = connected, red = server not running)

If server is not running:
```
│  ✗ Server not running           │
│                                 │
│  Start it with:                 │
│  $ yt-dlp-dj serve              │
```

### State 2: Loading

```
│  Fetching metadata...           │
│  ◐                              │
```

Simple spinner while waiting for `/api/preview` response.

### State 3: Preview / Edit

```
┌─────────────────────────────────┐
│  yt-dlp-dj                      │
│─────────────────────────────────│
│                                 │
│  Artist: [DJ Snake          ]   │
│  Title:  [Turn Down for What]   │
│  Genre:  [Trap              ]   │
│  Year:   [2014              ]   │
│  Label:  [Columbia Records  ]   │
│  Energy: [8                 ]   │
│  BPM:    [                  ]   │
│  Key:    [                  ]   │
│  Comment:[https://youtu.be/…]   │
│                                 │
│  Format: (●) Best ( ) MP3       │
│          ( ) FLAC ( ) M4A       │
│                                 │
│  ⓘ Enriched by Claude          │
│                                 │
│  [Download]                     │
│                                 │
└─────────────────────────────────┘
```

- All fields are editable text inputs
- Format is radio buttons
- Small indicator showing enrichment source ("Enriched by Claude" or "Basic parsing")
- Download button triggers `POST /api/download`

### State 4: Downloading

```
│  Downloading...                 │
│  ◐                              │
```

Download button disabled, spinner shown. In v2, could show progress via SSE.

### State 5: Complete

```
┌─────────────────────────────────┐
│  yt-dlp-dj                      │
│─────────────────────────────────│
│                                 │
│  ✓ Downloaded!                  │
│                                 │
│  DJ Snake - Turn Down for What  │
│  → ~/Music/DJ Library/          │
│                                 │
│  [Download Another]             │
│                                 │
└─────────────────────────────────┘
```

### State 6: Error

```
│  ✗ Download failed              │
│                                 │
│  Unsupported URL                │
│                                 │
│  [Try Again]                    │
```

## TypeScript Architecture

```
extension/src/
├── popup.ts       # Main popup logic: state machine, DOM manipulation, API calls
├── background.ts  # Service worker: badge updates (minimal)
├── options.ts     # Options page: server port configuration
├── types.ts       # Shared types (mirrors server Pydantic models)
└── api.ts         # HTTP client for talking to the local server
```

### `api.ts` — Server Client

```typescript
const BASE_URL = "http://localhost:9234";  // configurable via options

export async function healthCheck(): Promise<boolean> { ... }
export async function fetchPreview(url: string): Promise<PreviewResponse> { ... }
export async function requestDownload(req: DownloadRequest): Promise<DownloadResponse> { ... }
```

All API calls wrapped with error handling. Timeouts: 30s for preview (LLM can be slow), 120s for download.

### `popup.ts` — State Machine

Simple state machine driven by a `state` variable:

```typescript
type PopupState = "initial" | "loading" | "preview" | "downloading" | "complete" | "error";

let state: PopupState = "initial";

function render(state: PopupState): void {
  // Show/hide DOM sections based on state
}
```

No framework — vanilla TypeScript with direct DOM manipulation. The popup is small enough that React/Preact would be overhead.

## Options Page

`options.html` — Simple form to configure:
- Server port (default: 9234)
- Server host (default: localhost)

Stored in `chrome.storage.sync` so it persists across browser restarts.

## Background Service Worker

`background.ts` — Minimal:
- Listen for messages from popup (badge updates)
- Set badge text during download ("...")
- Clear badge on complete

## Styling

`popup.css` — Clean, minimal styling:
- System font stack
- 350px wide popup
- Dark/light follows system preference via `prefers-color-scheme`
- Simple form inputs with consistent padding
- Status indicators: green dot (connected), red dot (disconnected), checkmark (success), X (error)

## Build Pipeline

```json
// package.json scripts
{
  "build": "esbuild src/popup.ts src/background.ts src/options.ts src/api.ts --bundle --outdir=dist --format=esm",
  "watch": "esbuild src/*.ts --bundle --outdir=dist --format=esm --watch",
  "lint": "eslint src/",
  "format": "prettier --write src/",
  "typecheck": "tsc --noEmit"
}
```

`npm run watch` during development for instant rebuilds. Load as unpacked extension from the `extension/` directory in Chrome.

## Testing Strategy

- Manual testing with the actual extension loaded in Chrome
- TypeScript type checking catches most integration issues
- API client can be tested against a mock server or the real server
- No unit test framework for the extension — it's thin enough that type safety + manual testing covers it

## Success Criteria

- [ ] Extension loads in Chrome as unpacked extension
- [ ] Popup opens and shows current tab URL
- [ ] Health check shows server connection status
- [ ] "Fetch Metadata" calls server and displays results
- [ ] All metadata fields are editable
- [ ] Format selector works (Best / MP3 / FLAC / M4A)
- [ ] "Download" triggers server download and shows completion
- [ ] Error states display clearly
- [ ] Options page allows port configuration
- [ ] `npm run typecheck` passes
- [ ] `npm run lint` passes
- [ ] `npm run build` produces working dist/ output
