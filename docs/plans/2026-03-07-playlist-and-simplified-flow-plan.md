# Playlist Support & Simplified Download Flow — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the preview step, add one-click download and playlist support.

**Architecture:** Extension becomes a thin action bar (format picker + Download + Download Playlist) over the existing queue list. Server gains a `/api/resolve-playlist` endpoint and a revised `/api/download` that extracts its own raw metadata instead of requiring it from the client. Background worker is unchanged.

**Tech Stack:** TypeScript (Chrome extension), Python/FastAPI (server), yt-dlp, mutagen

---

### Task 1: Make `raw` optional in DownloadRequest and extract server-side

Currently `/api/download` requires `raw: RawMetadata` from the client (populated during preview). Since we're removing preview, the server must extract raw metadata itself when not provided.

**Files:**
- Modify: `server/models.py:56-79` (DownloadRequest)
- Modify: `server/app.py:82-189` (download endpoint)
- Modify: `tests/test_app.py` (update tests, add new test)

**Step 1: Make `raw` optional in the Pydantic model**

In `server/models.py`, change `DownloadRequest.raw` from required to optional:

```python
class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    raw: RawMetadata | None = None  # Optional — server extracts if missing
    format: str = "best"
    user_edited_fields: list[str] = []
    cookies: list[CookieItem] = []
```

**Step 2: Update download endpoint to extract raw when missing**

In `server/app.py`, at the top of the `download` function, add raw extraction:

```python
@app.post("/api/download", response_model=DownloadResponse)
async def download(req: DownloadRequest) -> DownloadResponse:
    cfg = load_config()

    # Extract raw metadata if not provided (new simplified flow)
    raw = req.raw
    if raw is None:
        try:
            raw = await extract_metadata(req.url, cookies=req.cookies)
        except DownloadError as e:
            raise HTTPException(
                status_code=500,
                detail={"error": "extraction_failed", "message": e.message, "url": e.url},
            ) from e

    filename = build_download_filename(req.metadata.artist, req.metadata.title)
    use_llm = cfg.llm.enabled and await is_claude_available()
    # ... rest uses `raw` instead of `req.raw` throughout
```

Replace all `req.raw` references in the function body with `raw`.

**Step 3: Write test for download without raw**

Add to `tests/test_app.py`:

```python
async def test_download_without_raw_extracts_metadata(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW),
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
```

**Step 4: Run tests**

```bash
cd /Users/donovanyohan/Documents/Programs/personal/yt-dlp-dj && uv run pytest tests/test_app.py -v
```

**Step 5: Commit**

```bash
git add server/models.py server/app.py tests/test_app.py
git commit -m "feat: make raw metadata optional in download request — server extracts when missing"
```

---

### Task 2: Add `/api/resolve-playlist` endpoint

**Files:**
- Modify: `server/downloader.py` (add resolve function)
- Modify: `server/models.py` (add request/response models)
- Modify: `server/app.py` (add endpoint)
- Modify: `tests/test_app.py` (add tests)

**Step 1: Add Pydantic models**

In `server/models.py`, add:

```python
class PlaylistTrack(BaseModel):
    url: str
    title: str

class ResolvePlaylistRequest(BaseModel):
    url: str
    cookies: list[CookieItem] = []

class ResolvePlaylistResponse(BaseModel):
    playlist_title: str
    tracks: list[PlaylistTrack]
```

**Step 2: Add resolve function to downloader**

In `server/downloader.py`, add:

```python
def _resolve_playlist_sync(url: str, cookies: list[CookieItem] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Resolve playlist to list of (url, title) tuples. Returns (playlist_title, tracks)."""
    with _cookie_file(cookies or []) as cookie_path:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
        }
        if cookie_path:
            ydl_opts["cookiefile"] = cookie_path
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info: dict[str, Any] | None = ydl.extract_info(url, download=False)
                if info is None:
                    raise DownloadError("No playlist data returned", url=url)

                playlist_title = str(info.get("title") or "Unknown Playlist")
                entries = info.get("entries") or []
                tracks: list[tuple[str, str]] = []
                for entry in entries:
                    if entry is None:
                        continue
                    video_url = entry.get("url") or entry.get("webpage_url") or ""
                    video_title = str(entry.get("title") or "Unknown")
                    if video_url:
                        tracks.append((video_url, video_title))
                return playlist_title, tracks
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(str(exc), url=url) from exc


async def resolve_playlist(url: str, cookies: list[CookieItem] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Resolve playlist URLs without downloading."""
    return await asyncio.to_thread(_resolve_playlist_sync, url, cookies)
```

**Step 3: Add endpoint to app.py**

```python
from server.downloader import DownloadError, download_audio, extract_metadata, resolve_playlist
from server.models import (
    # ... existing imports ...
    PlaylistTrack,
    ResolvePlaylistRequest,
    ResolvePlaylistResponse,
)

@app.post("/api/resolve-playlist", response_model=ResolvePlaylistResponse)
async def resolve_playlist_endpoint(req: ResolvePlaylistRequest) -> ResolvePlaylistResponse:
    try:
        playlist_title, tracks = await resolve_playlist(req.url, cookies=req.cookies)
    except DownloadError as e:
        raise HTTPException(
            status_code=404,
            detail={"error": "playlist_resolve_failed", "message": e.message, "url": e.url},
        ) from e

    return ResolvePlaylistResponse(
        playlist_title=playlist_title,
        tracks=[PlaylistTrack(url=url, title=title) for url, title in tracks],
    )
```

**Step 4: Write tests**

Add to `tests/test_app.py`:

```python
async def test_resolve_playlist_success(client: AsyncClient) -> None:
    mock_tracks = [
        ("https://www.youtube.com/watch?v=abc", "Track 1"),
        ("https://www.youtube.com/watch?v=def", "Track 2"),
    ]
    with patch(
        "server.app.resolve_playlist",
        new_callable=AsyncMock,
        return_value=("My Playlist", mock_tracks),
    ):
        response = await client.post(
            "/api/resolve-playlist",
            json={"url": "https://www.youtube.com/playlist?list=PLxyz"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["playlist_title"] == "My Playlist"
    assert len(data["tracks"]) == 2
    assert data["tracks"][0]["url"] == "https://www.youtube.com/watch?v=abc"


async def test_resolve_playlist_failure(client: AsyncClient) -> None:
    with patch(
        "server.app.resolve_playlist",
        new_callable=AsyncMock,
        side_effect=DownloadError("Not a playlist", url="https://example.com"),
    ):
        response = await client.post(
            "/api/resolve-playlist",
            json={"url": "https://example.com"},
        )
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "playlist_resolve_failed"
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_app.py -v
```

**Step 6: Commit**

```bash
git add server/downloader.py server/models.py server/app.py tests/test_app.py
git commit -m "feat: add /api/resolve-playlist endpoint for flat playlist extraction"
```

---

### Task 3: Add TypeScript types and API functions for new flow

**Files:**
- Modify: `extension/src/types.ts` (add playlist types, make QueueItem.raw nullable)
- Modify: `extension/src/api.ts` (add resolvePlaylist, remove fetchPreview)

**Step 1: Update types**

In `extension/src/types.ts`:

- Make `QueueItem.raw` nullable:
```typescript
raw: RawMetadata | null;
```

- Add playlist types:
```typescript
export interface PlaylistTrack {
  url: string;
  title: string;
}

export interface ResolvePlaylistResponse {
  playlist_title: string;
  tracks: PlaylistTrack[];
}
```

- Remove `PreviewResponse` interface (no longer used).

**Step 2: Update api.ts**

Remove `fetchPreview`. Add:

```typescript
export async function resolvePlaylist(url: string): Promise<ResolvePlaylistResponse> {
  const baseUrl = await getBaseUrl();
  const cookies = await getYouTubeCookies();
  const response = await fetchWithTimeout(
    `${baseUrl}/api/resolve-playlist`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookies }),
    },
    60000 // playlists can be large
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as ResolvePlaylistResponse;
}
```

**Step 3: Update background.ts to handle null raw**

In background.ts, the `DownloadRequest` build (line 44-51) sends `pending.raw`. Update the `DownloadRequest` type and the request body to conditionally include raw:

```typescript
const req: DownloadRequest = {
  url: pending.url,
  metadata: pending.metadata,
  raw: pending.raw,       // may be null — server will extract
  format: pending.format,
  user_edited_fields: pending.userEditedFields,
  cookies,
};
```

Update the `DownloadRequest` type in `types.ts`:
```typescript
export interface DownloadRequest {
  url: string;
  metadata: EnrichedMetadata;
  raw: RawMetadata | null;
  format: string;
  user_edited_fields: string[];
  cookies?: CookieData[];
}
```

**Step 4: Build and type-check**

```bash
cd extension && npm run build && npx tsc --noEmit
```

**Step 5: Commit**

```bash
git add extension/src/types.ts extension/src/api.ts extension/src/background.ts
git commit -m "feat: add playlist API types and make raw metadata nullable in extension"
```

---

### Task 4: Rewrite popup.html — replace preview form with action bar

**Files:**
- Modify: `extension/popup.html`

**Step 1: Replace the HTML body**

Replace sections `section-fetch`, `section-loading`, `section-preview`, and `section-fetch-error` with a single action bar section:

```html
<!-- Action bar -->
<section id="section-actions">
  <div class="action-bar">
    <select id="format-select" class="format-select">
      <option value="m4a">M4A</option>
      <option value="mp3">MP3</option>
      <option value="flac">FLAC</option>
      <option value="ogg">OGG</option>
    </select>
    <button id="btn-download" class="btn btn-primary" disabled>Download</button>
    <button id="btn-download-playlist" class="btn btn-secondary" hidden>Playlist</button>
  </div>
</section>

<!-- Error display (reusable) -->
<section id="section-error" hidden>
  <p class="error-heading">&#10007; Error</p>
  <p id="error-message" class="error-message"></p>
  <button id="btn-dismiss-error" class="btn btn-secondary">Dismiss</button>
</section>

<!-- Queue list (unchanged) -->
<section id="section-queue">
  <div id="queue-list" class="queue-list"></div>
</section>
```

**Step 2: Commit**

```bash
git add extension/popup.html
git commit -m "feat: replace preview form with action bar in popup HTML"
```

---

### Task 5: Add CSS for action bar

**Files:**
- Modify: `extension/popup.css`

**Step 1: Add action bar styles, remove unused preview styles**

Add:

```css
/* Action bar */
.action-bar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.format-select {
  padding: 7px 8px;
  font-size: 13px;
  background: var(--input-bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 5px;
  cursor: pointer;
  flex-shrink: 0;
}

.action-bar .btn {
  flex: 1;
}
```

Remove the `.format-group`, `.format-group legend`, `.radio-label`, `.enrichment-info`, `.loading-text` rules since those UI elements are gone.

**Step 2: Commit**

```bash
git add extension/popup.css
git commit -m "feat: add action bar CSS, remove unused preview styles"
```

---

### Task 6: Rewrite popup.ts — simplified flow logic

This is the largest task. The popup goes from a multi-step state machine to a simple action dispatcher.

**Files:**
- Rewrite: `extension/src/popup.ts`

**Step 1: Rewrite the module**

Key changes:
- Remove: `readMetadataFromForm`, `getSelectedFormat` (radio-based), `computeUserEditedFields`, `populatePreviewForm`, `showView`, `handleFetchMetadata`, the entire preview flow
- Keep: `renderQueueList`, `renderQueueItem`, `renderExpandableDetail`, `getStatusIcon`, `escapeHtml`, `escapeAttr`, `attachQueueListeners`, `handleSkipAnalyze`, `handleRetry`, `handleSaveTags`, `readEditFields`, `renderSegmentList`
- Add: `handleDownload`, `handleDownloadPlaylist`, format persistence, playlist URL detection

```typescript
import { healthCheck, requestRetag, resolvePlaylist } from "./api.js";
import { getEl } from "./dom.js";
import { readQueue, writeQueue } from "./queue-storage.js";
import type { EnrichedMetadata, QueueItem } from "./types.js";

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function getInput(id: string): HTMLInputElement {
  return getEl<HTMLInputElement>(id);
}

function stripPlaylistParams(url: string): string {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtube.com") || u.hostname.includes("youtu.be")) {
      u.searchParams.delete("list");
      u.searchParams.delete("index");
    }
    return u.toString();
  } catch {
    return url;
  }
}

function hasPlaylistParam(url: string): boolean {
  try {
    return new URL(url).searchParams.has("list");
  } catch {
    return false;
  }
}

function getSelectedFormat(): string {
  return (document.getElementById("format-select") as HTMLSelectElement)?.value ?? "m4a";
}

function placeholderMetadata(title: string, url: string): EnrichedMetadata {
  // Basic artist/title split from YouTube page title
  let artist = "";
  let trackTitle = title;
  if (title.includes(" - ")) {
    [artist, trackTitle] = title.split(" - ", 2);
  }
  return {
    artist: artist.trim(),
    title: trackTitle.trim(),
    album: null,
    genre: null,
    year: null,
    label: null,
    energy: null,
    bpm: null,
    key: null,
    cover_art_url: null,
    comment: url,
  };
}

// ... keep all render/queue functions unchanged (renderQueueList through attachQueueListeners) ...

function showError(msg: string): void {
  const section = document.getElementById("section-error");
  const msgEl = document.getElementById("error-message");
  if (section && msgEl) {
    msgEl.textContent = msg;
    section.hidden = false;
  }
}

function hideError(): void {
  const section = document.getElementById("section-error");
  if (section) section.hidden = true;
}

async function handleDownload(url: string, pageTitle: string): Promise<void> {
  const videoUrl = stripPlaylistParams(url);
  const format = getSelectedFormat();
  const metadata = placeholderMetadata(pageTitle, videoUrl);

  const item: QueueItem = {
    id: generateId(),
    url: videoUrl,
    metadata,
    raw: null,
    format,
    userEditedFields: [],
    status: "pending",
    addedAt: Date.now(),
  };

  const queue = await readQueue();
  queue.push(item);
  await writeQueue(queue);
  void chrome.runtime.sendMessage({ type: "queue_process" });
}

async function handleDownloadPlaylist(url: string): Promise<void> {
  const format = getSelectedFormat();
  const btn = document.getElementById("btn-download-playlist") as HTMLButtonElement;
  btn.disabled = true;
  btn.textContent = "Resolving...";

  try {
    const result = await resolvePlaylist(url);
    const queue = await readQueue();
    for (const track of result.tracks) {
      const metadata = placeholderMetadata(track.title, track.url);
      queue.push({
        id: generateId(),
        url: track.url,
        metadata,
        raw: null,
        format,
        userEditedFields: [],
        status: "pending",
        addedAt: Date.now(),
      });
    }
    await writeQueue(queue);
    void chrome.runtime.sendMessage({ type: "queue_process" });
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
  } finally {
    btn.disabled = false;
    btn.textContent = "Playlist";
  }
}

async function init(): Promise<void> {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const currentUrl = tabs[0]?.url ?? "";
  const pageTitle = tabs[0]?.title ?? "";

  const isConnected = await healthCheck();
  const statusEl = document.getElementById("server-status");
  if (statusEl) {
    statusEl.className = isConnected ? "status-dot connected" : "status-dot disconnected";
    statusEl.title = isConnected ? "Connected" : "Server not running";
  }

  // Format persistence
  const stored = await chrome.storage.sync.get({ format: "m4a" });
  const formatSelect = document.getElementById("format-select") as HTMLSelectElement;
  if (formatSelect) formatSelect.value = stored["format"] as string;

  const downloadBtn = getEl<HTMLButtonElement>("btn-download");
  downloadBtn.disabled = !isConnected || !currentUrl;

  // Show playlist button only when URL has list= param
  const playlistBtn = document.getElementById("btn-download-playlist") as HTMLButtonElement;
  if (playlistBtn) {
    playlistBtn.hidden = !hasPlaylistParam(currentUrl);
    playlistBtn.disabled = !isConnected;
  }

  const queue = await readQueue();
  renderQueueList(queue);

  if (queue.length > 10) {
    const sorted = queue.slice().sort((a, b) => b.addedAt - a.addedAt);
    await writeQueue(sorted.slice(0, 10));
  }
}
```

DOMContentLoaded handler:

```typescript
document.addEventListener("DOMContentLoaded", () => {
  const versionEl = document.getElementById("ext-version");
  if (versionEl) {
    versionEl.textContent = `v${chrome.runtime.getManifest().version}`;
  }

  void init();

  // Persist format selection
  document.getElementById("format-select")?.addEventListener("change", () => {
    void chrome.storage.sync.set({ format: getSelectedFormat() });
  });

  getEl<HTMLButtonElement>("btn-download").addEventListener("click", () => {
    void (async () => {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const url = tabs[0]?.url ?? "";
      const title = tabs[0]?.title ?? "";
      void handleDownload(url, title);
    })();
  });

  document.getElementById("btn-download-playlist")?.addEventListener("click", () => {
    void (async () => {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const url = tabs[0]?.url ?? "";
      void handleDownloadPlaylist(url);
    })();
  });

  document.getElementById("btn-dismiss-error")?.addEventListener("click", () => {
    hideError();
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes["queue"]) {
      const newQueue = (changes["queue"].newValue as QueueItem[] | undefined) ?? [];
      renderQueueList(newQueue);
    }
  });
});
```

**Step 2: Build and type-check**

```bash
cd extension && npm run build && npx tsc --noEmit
```

**Step 3: Commit**

```bash
git add extension/src/popup.ts
git commit -m "feat: rewrite popup.ts — one-click download and playlist support"
```

---

### Task 7: Clean up unused code

**Files:**
- Modify: `extension/src/api.ts` (remove fetchPreview)
- Modify: `extension/src/types.ts` (remove PreviewResponse)
- Optionally: `server/app.py` (remove /api/preview endpoint)
- Optionally: `server/models.py` (remove PreviewRequest, PreviewResponse)

**Step 1: Remove fetchPreview from api.ts**

Delete the `fetchPreview` function entirely. Keep `fetchWithTimeout`, `getBaseUrl`, `healthCheck`, `requestRetag`, `requestAnalyze`, `getYouTubeCookies`, and add `resolvePlaylist`.

**Step 2: Remove PreviewResponse from types.ts**

Delete the `PreviewResponse` interface.

**Step 3: Remove server preview endpoint and models**

In `server/app.py`: remove the `/api/preview` endpoint function.
In `server/models.py`: remove `PreviewRequest` and `PreviewResponse`.
In `tests/test_app.py`: remove `test_preview_success`, `test_preview_extraction_error`, `test_preview_missing_url`.

**Step 4: Run all tests**

```bash
uv run pytest -v
```

**Step 5: Build extension and type-check**

```bash
cd extension && npm run build && npx tsc --noEmit
```

**Step 6: Lint everything**

```bash
uv run ruff check . && uv run ruff format --check .
cd extension && npm run lint
```

**Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove preview flow — clean up unused code on server and extension"
```

---

### Task 8: End-to-end manual test

**Step 1: Rebuild and reload**

```bash
cd extension && npm run build
```

Reload extension in Chrome.

**Step 2: Test single video download**

- Navigate to any YouTube video (not in a playlist)
- Open extension — should see format dropdown + Download button, no Playlist button
- Select format, click Download
- Verify item appears in queue as "pending" then "downloading" then "complete"

**Step 3: Test playlist download**

- Navigate to a YouTube video that's in a playlist (URL has `&list=...`)
- Open extension — should see both Download and Playlist buttons
- Click Download — should queue only the current video
- Click Playlist — should show "Resolving..." then queue all playlist tracks

**Step 4: Test format persistence**

- Change format to MP3, close and reopen popup — should still be MP3

**Step 5: Test error handling**

- Disconnect server, try Download — should show error message with dismiss button

**Step 6: Commit any fixes**

---

## Task Summary

| Task | Description | Scope |
|------|------------|-------|
| 1 | Make `raw` optional in DownloadRequest, server extracts when missing | Server |
| 2 | Add `/api/resolve-playlist` endpoint | Server |
| 3 | Add TypeScript types and API functions | Extension |
| 4 | Rewrite popup.html with action bar | Extension |
| 5 | Add action bar CSS, remove preview CSS | Extension |
| 6 | Rewrite popup.ts with new flow | Extension |
| 7 | Clean up unused preview code | Both |
| 8 | End-to-end manual test | Manual |
