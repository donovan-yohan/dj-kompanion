import { healthCheck, requestRetag, requestSyncVdj, resolvePlaylist } from "./api.js";
import { getEl } from "./dom.js";
import { readQueue, writeQueue } from "./queue-storage.js";
import type { EnrichedMetadata, QueueItem } from "./types.js";

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
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

function renderQueueList(queue: QueueItem[]): void {
  const listEl = document.getElementById("queue-list");
  if (!listEl) return;

  const recent = queue
    .slice()
    .sort((a, b) => b.addedAt - a.addedAt)
    .slice(0, 10);

  if (recent.length === 0) {
    listEl.innerHTML = "";
    return;
  }

  listEl.innerHTML = recent.map((item) => renderQueueItem(item)).join("");
  attachQueueListeners(listEl);
}

function renderQueueItem(item: QueueItem): string {
  const statusIcon = getStatusIcon(item);
  const enrichmentIcon = item.enrichmentSource === "claude" ? " ✨" : "";
  const title = `${item.metadata.artist} - ${item.metadata.title}`;

  let detail = "";
  if ((item.status === "complete" || item.status === "analyzed") && item.filepath) {
    detail = `<div class="queue-item-path">→ ${escapeHtml(item.filepath)}</div>`;
  }
  if (item.status === "analyzed" && item.analysis) {
    detail += `<div class="queue-item-analysis">BPM: ${item.analysis.bpm.toFixed(1)} | Key: ${escapeHtml(item.analysis.key_camelot)} | ${item.analysis.segments.length} sections</div>`;
  }
  if (item.status === "analyzing") {
    detail = `<div class="queue-item-path">Analyzing... <button class="btn btn-secondary btn-skip-analyze" data-id="${item.id}">Skip</button></div>`;
  }
  if (item.status === "error" && item.error) {
    detail = `
      <div class="queue-item-error">
        <span>${escapeHtml(item.error)}</span>
        <button class="btn btn-secondary btn-retry" data-id="${item.id}">Retry</button>
      </div>`;
  }

  const expandableDetail =
    item.status === "complete" || item.status === "analyzed"
      ? renderExpandableDetail(item)
      : "";

  return `
    <div class="queue-item" data-id="${item.id}" data-status="${item.status}">
      <div class="queue-item-header">
        <span class="queue-item-status">${statusIcon}${enrichmentIcon}</span>
        <span class="queue-item-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
      </div>
      ${detail}
      ${expandableDetail}
    </div>`;
}

function renderSegmentList(item: QueueItem): string {
  if (!item.analysis || item.analysis.segments.length === 0) return "";
  const rows = item.analysis.segments
    .map(
      (seg) =>
        `<div class="segment-row"><span class="segment-label">${escapeHtml(seg.label)}</span><span class="segment-time">${seg.start.toFixed(1)}s – ${seg.end.toFixed(1)}s</span><span class="segment-bars">${seg.bars} bars</span></div>`
    )
    .join("");
  return `<div class="queue-item-segments"><div class="segments-header">Sections</div>${rows}</div>`;
}

function renderExpandableDetail(item: QueueItem): string {
  const m = item.metadata;
  return `
    <div class="queue-item-detail">
      <div class="field-row"><label>Artist</label><input type="text" class="edit-field" data-field="artist" value="${escapeAttr(m.artist)}" /></div>
      <div class="field-row"><label>Title</label><input type="text" class="edit-field" data-field="title" value="${escapeAttr(m.title)}" /></div>
      <div class="field-row"><label>Genre</label><input type="text" class="edit-field" data-field="genre" value="${escapeAttr(m.genre ?? "")}" /></div>
      <div class="field-row"><label>Year</label><input type="text" class="edit-field" data-field="year" value="${m.year != null ? m.year : ""}" inputmode="numeric" /></div>
      <div class="field-row"><label>Label</label><input type="text" class="edit-field" data-field="label" value="${escapeAttr(m.label ?? "")}" /></div>
      <div class="field-row"><label>Energy</label><input type="text" class="edit-field" data-field="energy" value="${m.energy != null ? m.energy : ""}" inputmode="numeric" /></div>
      <div class="field-row"><label>BPM</label><input type="text" class="edit-field" data-field="bpm" value="${m.bpm != null ? m.bpm : ""}" inputmode="decimal" /></div>
      <div class="field-row"><label>Key</label><input type="text" class="edit-field" data-field="key" value="${escapeAttr(m.key ?? "")}" /></div>
      <div class="field-row"><label>Comment</label><input type="text" class="edit-field" data-field="comment" value="${escapeAttr(m.comment)}" /></div>
      <div class="btn-row">
        <button class="btn btn-primary btn-save-tags" data-id="${item.id}">Save Tags</button>
        <button class="btn btn-secondary btn-cancel-edit" data-id="${item.id}">Cancel</button>
      </div>
      ${renderSegmentList(item)}
    </div>`;
}

function getStatusIcon(item: QueueItem): string {
  switch (item.status) {
    case "pending":
      return "⏳";
    case "downloading":
      return '<span class="spinner-inline"></span>';
    case "complete":
      return "✓";
    case "analyzing":
      return '<span class="spinner-inline"></span>';
    case "analyzed":
      return "✓";
    case "error":
      return "✗";
  }
}

function escapeHtml(str: string): string {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function attachQueueListeners(listEl: HTMLElement): void {
  listEl.querySelectorAll<HTMLButtonElement>(".btn-retry").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset["id"];
      if (id) void handleRetry(id);
    });
  });

  listEl.querySelectorAll<HTMLButtonElement>(".btn-skip-analyze").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset["id"];
      if (id) void handleSkipAnalyze(id);
    });
  });

  listEl.querySelectorAll<HTMLButtonElement>(".btn-save-tags").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.dataset["id"];
      if (id) void handleSaveTags(id);
    });
  });

  listEl.querySelectorAll<HTMLButtonElement>(".btn-cancel-edit").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const itemEl = btn.closest(".queue-item");
      if (itemEl) itemEl.classList.remove("expanded");
    });
  });

  listEl.querySelectorAll<HTMLElement>(".queue-item-header").forEach((header) => {
    const itemEl = header.closest<HTMLElement>(".queue-item");
    if (
      itemEl &&
      (itemEl.dataset["status"] === "complete" || itemEl.dataset["status"] === "analyzed")
    ) {
      header.addEventListener("click", () => {
        itemEl.classList.toggle("expanded");
      });
    }
  });
}

async function handleSkipAnalyze(id: string): Promise<void> {
  const queue = await readQueue();
  const idx = queue.findIndex((item) => item.id === id);
  if (idx !== -1) {
    queue[idx] = { ...queue[idx], status: "complete" };
    await writeQueue(queue);
  }
}

async function handleRetry(id: string): Promise<void> {
  const queue = await readQueue();
  const idx = queue.findIndex((item) => item.id === id);
  if (idx !== -1) {
    queue[idx] = { ...queue[idx], status: "pending", error: undefined };
    await writeQueue(queue);
    void chrome.runtime.sendMessage({ type: "queue_process" });
  }
}

async function handleSaveTags(id: string): Promise<void> {
  const queue = await readQueue();
  const item = queue.find((i) => i.id === id);
  if (!item || !item.filepath) return;

  const itemEl = document.querySelector<HTMLElement>(`.queue-item[data-id="${id}"]`);
  if (!itemEl) return;

  const metadata = readEditFields(itemEl);

  try {
    const result = await requestRetag({ filepath: item.filepath, metadata });
    const freshQueue = await readQueue();
    const freshIdx = freshQueue.findIndex((i) => i.id === id);
    if (freshIdx !== -1) {
      freshQueue[freshIdx] = {
        ...freshQueue[freshIdx],
        metadata,
        filepath: result.filepath,
      };
      await writeQueue(freshQueue);
    }
    itemEl.classList.remove("expanded");
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    alert(`Failed to save tags: ${errMsg}`);
  }
}

function readEditFields(itemEl: HTMLElement): EnrichedMetadata {
  const get = (field: string): string =>
    itemEl.querySelector<HTMLInputElement>(`.edit-field[data-field="${field}"]`)?.value ?? "";

  return {
    artist: get("artist"),
    title: get("title"),
    album: null,
    genre: get("genre") || null,
    year: get("year") !== "" ? parseInt(get("year"), 10) : null,
    label: get("label") || null,
    energy: get("energy") !== "" ? parseInt(get("energy"), 10) : null,
    bpm: get("bpm") !== "" ? parseFloat(get("bpm")) : null,
    key: get("key") || null,
    cover_art_url: null,
    comment: get("comment"),
  };
}

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

async function handleSyncVdj(): Promise<void> {
  const btn = document.getElementById("btn-sync-vdj") as HTMLButtonElement;
  const statusEl = document.getElementById("sync-status");
  btn.disabled = true;
  btn.textContent = "Syncing...";
  if (statusEl) statusEl.textContent = "";

  try {
    const result = await requestSyncVdj();
    if (result.refused) {
      if (statusEl) statusEl.textContent = "VDJ is running — close it first";
    } else {
      if (statusEl) statusEl.textContent = `Synced ${result.synced}, skipped ${result.skipped}`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = err instanceof Error ? err.message : String(err);
  } finally {
    btn.disabled = false;
    btn.textContent = "Sync to VDJ";
  }
}

async function init(): Promise<void> {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const currentUrl = tabs[0]?.url ?? "";

  const isConnected = await healthCheck();
  const statusEl = document.getElementById("server-status");
  if (statusEl) {
    statusEl.className = isConnected ? "status-dot connected" : "status-dot disconnected";
    statusEl.title = isConnected ? "Connected" : "Server not running";
  }

  // Enable sync button when connected
  const syncBtn = document.getElementById("btn-sync-vdj") as HTMLButtonElement;
  if (syncBtn) syncBtn.disabled = !isConnected;

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

  document.getElementById("btn-sync-vdj")?.addEventListener("click", () => {
    void handleSyncVdj();
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes["queue"]) {
      const newQueue = (changes["queue"].newValue as QueueItem[] | undefined) ?? [];
      renderQueueList(newQueue);
    }
  });
});
