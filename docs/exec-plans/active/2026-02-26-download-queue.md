# Download Queue

> **Status**: Active | **Created**: 2026-02-26 | **Last Updated**: 2026-02-26
> **Design Doc**: `docs/design-docs/2026-02-26-download-queue-design.md`
> **For Claude:** Use /harness:orchestrate to execute this plan.

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-02-26 | Design | Preview then queue (not skip-preview) | User wants to review/edit metadata before queueing |
| 2026-02-26 | Design | Service worker processes downloads | Popup can close while downloads continue |
| 2026-02-26 | Design | chrome.storage.local for persistence | Queue survives browser restart, simple API |
| 2026-02-26 | Design | Manual retry (not auto-retry) | User decides when to retry failed downloads |
| 2026-02-26 | Design | New /api/retag endpoint | Re-write tags without re-downloading the file |
| 2026-02-26 | Design | Sequential download processing | One at a time to avoid overwhelming the server |

## Progress

- [ ] Task 1: Server — add retag endpoint and update download response
- [ ] Task 2: Extension types — add QueueItem and retag interfaces
- [ ] Task 3: Extension API — add requestRetag function
- [ ] Task 4: Service worker — download processing loop
- [ ] Task 5: Popup HTML — queue-based layout
- [ ] Task 6: Popup CSS — queue item styles
- [ ] Task 7: Popup TS — queue renderer and inline preview
- [ ] Task 8: Integration test — end-to-end build and typecheck

## Surprises & Discoveries

_None yet — updated during execution by /harness:orchestrate._

## Plan Drift

_None yet — updated when tasks deviate from plan during execution._

---

## Task 1: Server — add retag endpoint and update download response

**Goal:** Add `POST /api/retag` endpoint and include `metadata` in the download response so the extension can display enriched values.

**Files:**
- Modify: `server/models.py`
- Modify: `server/app.py`
- Modify: `tests/test_app.py`

### Step 1: Add RetagRequest and RetagResponse models

In `server/models.py`, add after `DownloadResponse`:

```python
class RetagRequest(BaseModel):
    filepath: str
    metadata: EnrichedMetadata


class RetagResponse(BaseModel):
    status: str
    filepath: str
```

### Step 2: Add metadata field to DownloadResponse

In `server/models.py`, update `DownloadResponse`:

```python
class DownloadResponse(BaseModel):
    status: str
    filepath: str
    enrichment_source: Literal["claude", "basic", "none"] = "none"
    metadata: EnrichedMetadata | None = None
```

### Step 3: Add retag endpoint to app.py

In `server/app.py`, add the retag endpoint:

```python
from server.models import (
    DownloadRequest,
    DownloadResponse,
    HealthResponse,
    PreviewRequest,
    PreviewResponse,
    RetagRequest,
    RetagResponse,
)

@app.post("/api/retag", response_model=RetagResponse)
async def retag(req: RetagRequest) -> RetagResponse:
    filepath = Path(req.filepath)
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "file_not_found", "message": f"File not found: {req.filepath}"},
        )

    try:
        final_path = tag_file(filepath, req.metadata)
    except TaggingError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "tagging_failed",
                "message": e.message,
                "filepath": str(e.filepath),
            },
        ) from e

    return RetagResponse(status="ok", filepath=str(final_path))
```

### Step 4: Include metadata in download response

In `server/app.py`, update the download endpoint return to include `metadata=final_metadata`:

```python
    return DownloadResponse(
        status="complete",
        filepath=str(final_path),
        enrichment_source=enrichment_source,
        metadata=final_metadata,
    )
```

### Step 5: Add tests for retag endpoint

In `tests/test_app.py`, add tests:

1. `test_retag_success` — mock `tag_file`, verify 200 response with new filepath
2. `test_retag_file_not_found` — non-existent filepath returns 404
3. `test_retag_tagging_error` — `TaggingError` returns 500

### Step 6: Verify

```bash
uv run pytest tests/test_app.py -x
uv run mypy server/
```

---

## Task 2: Extension types — add QueueItem and retag interfaces

**Goal:** Add `QueueItem`, `RetagRequest`, `RetagResponse` interfaces and update `DownloadResponse`.

**Files:**
- Modify: `extension/src/types.ts`

### Step 1: Update DownloadResponse

Add `metadata` field:

```typescript
export interface DownloadResponse {
  status: string;
  filepath: string;
  enrichment_source: "claude" | "basic" | "none";
  metadata?: EnrichedMetadata;
}
```

### Step 2: Add QueueItem interface

```typescript
export interface QueueItem {
  id: string;
  url: string;
  metadata: EnrichedMetadata;
  raw: RawMetadata;
  format: string;
  userEditedFields: string[];
  status: "pending" | "downloading" | "complete" | "error";
  enrichmentSource?: "claude" | "basic" | "none";
  filepath?: string;
  error?: string;
  addedAt: number;
}
```

### Step 3: Add retag types

```typescript
export interface RetagRequest {
  filepath: string;
  metadata: EnrichedMetadata;
}

export interface RetagResponse {
  status: string;
  filepath: string;
}
```

### Step 4: Verify

```bash
cd extension && npx tsc --noEmit
```

---

## Task 3: Extension API — add requestRetag function

**Goal:** Add `requestRetag()` to `api.ts` and export `getBaseUrl` for use by the service worker.

**Files:**
- Modify: `extension/src/api.ts`

### Step 1: Export getBaseUrl and fetchWithTimeout

The service worker needs to call the server directly. Change `getBaseUrl` and `fetchWithTimeout` from private to exported:

```typescript
export async function getBaseUrl(): Promise<string> { ... }
export async function fetchWithTimeout(...): Promise<Response> { ... }
```

### Step 2: Add requestRetag function

```typescript
export async function requestRetag(req: RetagRequest): Promise<RetagResponse> {
  const baseUrl = await getBaseUrl();
  const response = await fetchWithTimeout(
    `${baseUrl}/api/retag`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    },
    30000,
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as RetagResponse;
}
```

### Step 3: Verify

```bash
cd extension && npx tsc --noEmit
```

---

## Task 4: Service worker — download processing loop

**Goal:** Rewrite `background.ts` to process downloads from the queue in `chrome.storage.local`.

**Files:**
- Rewrite: `extension/src/background.ts`

### Step 1: Define message types

```typescript
type QueueMessage =
  | { type: "queue_process" }
  | { type: "badge_set"; text: string; color: string }
  | { type: "badge_clear" };
```

### Step 2: Implement queue storage helpers

```typescript
import type { QueueItem, DownloadRequest } from "./types.js";

async function readQueue(): Promise<QueueItem[]> {
  const data = await chrome.storage.local.get("queue");
  return (data["queue"] as QueueItem[] | undefined) ?? [];
}

async function writeQueue(queue: QueueItem[]): Promise<void> {
  await chrome.storage.local.set({ queue });
}

async function updateItem(id: string, updates: Partial<QueueItem>): Promise<void> {
  const queue = await readQueue();
  const idx = queue.findIndex((item) => item.id === id);
  if (idx !== -1) {
    queue[idx] = { ...queue[idx], ...updates };
    await writeQueue(queue);
  }
}
```

### Step 3: Implement processing loop

```typescript
let processing = false;

async function processQueue(): Promise<void> {
  if (processing) return;
  processing = true;

  try {
    while (true) {
      const queue = await readQueue();
      const pending = queue.find((item) => item.status === "pending");
      if (!pending) break;

      await updateItem(pending.id, { status: "downloading" });
      await updateBadge();

      try {
        const req: DownloadRequest = {
          url: pending.url,
          metadata: pending.metadata,
          raw: pending.raw,
          format: pending.format,
          user_edited_fields: pending.userEditedFields,
        };

        const baseUrl = await getBaseUrl();
        const response = await fetchWithTimeout(
          `${baseUrl}/api/download`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(req),
          },
          120000,
        );

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`Server error ${response.status}: ${text}`);
        }

        const result = await response.json();
        await updateItem(pending.id, {
          status: "complete",
          filepath: result.filepath,
          enrichmentSource: result.enrichment_source,
          metadata: result.metadata ?? pending.metadata,
        });
      } catch (err) {
        await updateItem(pending.id, {
          status: "error",
          error: err instanceof Error ? err.message : String(err),
        });
      }

      await updateBadge();
    }
  } finally {
    processing = false;
    await updateBadge();
  }
}
```

### Step 4: Badge helper

```typescript
async function updateBadge(): Promise<void> {
  const queue = await readQueue();
  const active = queue.filter((i) => i.status === "pending" || i.status === "downloading").length;
  if (active > 0) {
    await chrome.action.setBadgeText({ text: String(active) });
    await chrome.action.setBadgeBackgroundColor({ color: "#3b82f6" });
  } else {
    await chrome.action.setBadgeText({ text: "" });
  }
}
```

### Step 5: Message listener and stale recovery

```typescript
chrome.runtime.onMessage.addListener((message: QueueMessage) => {
  if (message.type === "queue_process") {
    void processQueue();
  } else if (message.type === "badge_set") {
    void chrome.action.setBadgeText({ text: message.text });
    void chrome.action.setBadgeBackgroundColor({ color: message.color });
  } else if (message.type === "badge_clear") {
    void chrome.action.setBadgeText({ text: "" });
  }
});

// On service worker start, recover stale "downloading" items
chrome.runtime.onStartup.addListener(() => {
  void (async () => {
    const queue = await readQueue();
    let changed = false;
    for (const item of queue) {
      if (item.status === "downloading") {
        item.status = "pending";
        changed = true;
      }
    }
    if (changed) {
      await writeQueue(queue);
      void processQueue();
    }
  })();
});
```

### Step 6: Verify

```bash
cd extension && npx tsc --noEmit
```

---

## Task 5: Popup HTML — queue-based layout

**Goal:** Replace the single-download sections with a queue view + inline preview form.

**Files:**
- Rewrite: `extension/popup.html`

### Step 1: New HTML structure

Replace all `<section>` elements with:

```html
<header>
  <h1>dj-kompanion</h1>
  <span id="server-status" class="status-dot" title="Checking..."></span>
</header>

<!-- Fetch / Preview area -->
<section id="section-fetch">
  <button id="btn-fetch" class="btn btn-primary" disabled>Fetch from Current URL</button>
</section>

<section id="section-loading" hidden>
  <p class="loading-text">Fetching metadata...</p>
  <div class="spinner"></div>
</section>

<section id="section-preview" hidden>
  <!-- Same metadata form as today, but with Cancel button added -->
  <form id="metadata-form" autocomplete="off">
    <!-- ... existing field-rows ... -->
    <!-- ... existing format radio group ... -->
    <p id="enrichment-source" class="enrichment-info"></p>
    <div class="btn-row">
      <button id="btn-queue" type="button" class="btn btn-primary">Download</button>
      <button id="btn-cancel-preview" type="button" class="btn btn-secondary">Cancel</button>
    </div>
  </form>
</section>

<!-- Queue list -->
<section id="section-queue">
  <div id="queue-list" class="queue-list">
    <!-- Queue items rendered dynamically -->
  </div>
</section>
```

Keep the script tag at the bottom: `<script src="dist/popup.js"></script>`

### Step 2: Verify

```bash
cd extension && npm run build
```

---

## Task 6: Popup CSS — queue item styles

**Goal:** Add styles for queue items, scrollable list, expandable detail, status icons.

**Files:**
- Modify: `extension/popup.css`

### Step 1: Queue list container

```css
.queue-list {
  max-height: 300px;
  overflow-y: auto;
  border-top: 1px solid var(--border);
}
```

### Step 2: Queue item styles

```css
.queue-item {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}

.queue-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.queue-item-status { flex-shrink: 0; font-size: 14px; }
.queue-item-title { flex: 1; font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-item-path { font-size: 11px; color: var(--text-muted); word-break: break-all; margin-top: 2px; }
.queue-item-error { font-size: 11px; color: var(--error); margin-top: 2px; display: flex; align-items: center; gap: 6px; }
.queue-item-error .btn { width: auto; padding: 2px 8px; font-size: 11px; }
```

### Step 3: Expandable detail view

```css
.queue-item-detail { display: none; padding-top: 8px; }
.queue-item.expanded .queue-item-detail { display: block; }
.btn-row { display: flex; gap: 8px; margin-top: 8px; }
.btn-row .btn { flex: 1; }
```

### Step 4: Verify

```bash
cd extension && npm run build
```

---

## Task 7: Popup TS — queue renderer and inline preview

**Goal:** Rewrite `popup.ts` to render the queue list, handle inline preview, retag, and retry.

**Files:**
- Rewrite: `extension/src/popup.ts`

### Step 1: Imports and state

```typescript
import { fetchPreview, healthCheck, requestRetag } from "./api.js";
import { getEl } from "./dom.js";
import type { EnrichedMetadata, QueueItem, RawMetadata } from "./types.js";

let currentUrl = "";
let initialMetadata: EnrichedMetadata | null = null;
let previewRaw: RawMetadata | null = null;
```

### Step 2: Queue storage helpers (read-only from popup)

```typescript
async function readQueue(): Promise<QueueItem[]> {
  const data = await chrome.storage.local.get("queue");
  return (data["queue"] as QueueItem[] | undefined) ?? [];
}

async function writeQueue(queue: QueueItem[]): Promise<void> {
  await chrome.storage.local.set({ queue });
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
```

### Step 3: Queue list renderer

```typescript
function renderQueueList(queue: QueueItem[]): void {
  const listEl = getEl<HTMLDivElement>("queue-list");
  const recent = queue.slice().sort((a, b) => b.addedAt - a.addedAt).slice(0, 10);

  if (recent.length === 0) {
    listEl.innerHTML = "";
    return;
  }

  listEl.innerHTML = recent.map((item) => renderQueueItem(item)).join("");
  // Attach event listeners for retry, expand/collapse, save tags
  attachQueueItemListeners(listEl, recent);
}
```

### Step 4: Render individual queue item

Each item shows: status icon, title, path/error, and is clickable to expand for completed items.

Status icons:
- `pending`: `⏳`
- `downloading`: `◐` (with CSS animation)
- `complete`: `✓` (green), plus `✨` if `enrichmentSource === "claude"`
- `error`: `✗` (red) with retry button

### Step 5: Inline preview form handlers

- `handleFetchMetadata()` — same as today, shows section-preview, hides section-fetch
- `handleQueueDownload()` — reads form, builds QueueItem with status `"pending"`, writes to storage, sends `chrome.runtime.sendMessage({ type: "queue_process" })`, collapses form back to fetch button
- `handleCancelPreview()` — hides preview, shows fetch button

### Step 6: Expand/collapse completed items with edit form

Clicking a completed item renders inline edit fields pre-populated with `item.metadata`. "Save Tags" calls `requestRetag()`, updates the item in storage. "Cancel" collapses.

### Step 7: Retry handler

Clicking "Retry" on an error item: update status to `"pending"`, write to storage, send `queue_process` message.

### Step 8: Live updates via storage listener

```typescript
chrome.storage.onChanged.addListener((changes) => {
  if (changes["queue"]) {
    const newQueue = changes["queue"].newValue as QueueItem[];
    renderQueueList(newQueue);
  }
});
```

### Step 9: Init

```typescript
async function init(): Promise<void> {
  // Get current URL
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tabs[0]?.url ?? "";

  // Health check
  const isConnected = await healthCheck();
  // Update status dot in header
  // Enable/disable fetch button

  // Render existing queue
  const queue = await readQueue();
  renderQueueList(queue);

  // Prune old items beyond 10
  if (queue.length > 10) {
    const sorted = queue.sort((a, b) => b.addedAt - a.addedAt);
    await writeQueue(sorted.slice(0, 10));
  }
}
```

### Step 10: Verify

```bash
cd extension && npx tsc --noEmit && npm run build
```

---

## Task 8: Integration test — end-to-end build and typecheck

**Goal:** Verify the full extension builds, typechecks, and lints cleanly.

**Files:**
- No changes — verification only

### Step 1: TypeScript strict check

```bash
cd extension && npx tsc --noEmit
```

### Step 2: Build

```bash
cd extension && npm run build
```

### Step 3: Lint

```bash
cd extension && npm run lint
```

### Step 4: Python tests and typecheck

```bash
uv run pytest -x
uv run mypy server/
```

### Step 5: Manual smoke test instructions

Load the unpacked extension in Chrome and verify:
1. Popup opens showing "Fetch from Current URL" button + empty queue
2. Status dot shows green when server is running
3. Fetch metadata shows inline form
4. "Download" adds item to queue list
5. Queue items update status as download progresses
6. Closing and reopening popup preserves queue state
7. Completed items show ✨ when Claude enrichment was used
8. Clicking completed item expands metadata editor
9. "Save Tags" re-writes tags via retag endpoint
10. "Retry" re-queues failed items

---

## Outcomes & Retrospective

_Filled by /harness:complete when work is done._

**What worked:**
-

**What didn't:**
-

**Learnings to codify:**
-
