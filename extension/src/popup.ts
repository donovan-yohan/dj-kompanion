import { fetchPreview, healthCheck, requestRetag } from "./api.js";
import { getEl } from "./dom.js";
import { readQueue, writeQueue } from "./queue-storage.js";
import type { EnrichedMetadata, QueueItem, RawMetadata } from "./types.js";

let currentUrl = "";
let initialMetadata: EnrichedMetadata | null = null;
let previewRaw: RawMetadata | null = null;

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function getInput(id: string): HTMLInputElement {
  return getEl<HTMLInputElement>(id);
}

function readMetadataFromForm(): EnrichedMetadata {
  return {
    artist: getInput("field-artist").value,
    title: getInput("field-title").value,
    album: null,
    genre: getInput("field-genre").value || null,
    year: getInput("field-year").value !== "" ? parseInt(getInput("field-year").value, 10) : null,
    label: getInput("field-label").value || null,
    energy:
      getInput("field-energy").value !== "" ? parseInt(getInput("field-energy").value, 10) : null,
    bpm: getInput("field-bpm").value !== "" ? parseFloat(getInput("field-bpm").value) : null,
    key: getInput("field-key").value || null,
    cover_art_url: null,
    comment: getInput("field-comment").value,
  };
}

function getSelectedFormat(): string {
  const radios = Array.from(document.querySelectorAll<HTMLInputElement>('input[name="format"]'));
  for (const radio of radios) {
    if (radio.checked) return radio.value;
  }
  return "best";
}

function computeUserEditedFields(current: EnrichedMetadata): string[] {
  if (initialMetadata === null) return [];
  const fields: Array<keyof EnrichedMetadata> = [
    "artist",
    "title",
    "genre",
    "year",
    "label",
    "energy",
    "bpm",
    "key",
    "comment",
  ];
  return fields.filter((field) => {
    const initial = initialMetadata![field];
    const now = current[field];
    return String(initial ?? "") !== String(now ?? "");
  });
}

function populatePreviewForm(metadata: EnrichedMetadata, source: string, url: string): void {
  getInput("field-artist").value = metadata.artist;
  getInput("field-title").value = metadata.title;
  getInput("field-genre").value = metadata.genre ?? "";
  getInput("field-year").value = metadata.year != null ? String(metadata.year) : "";
  getInput("field-label").value = metadata.label ?? "";
  getInput("field-energy").value = metadata.energy != null ? String(metadata.energy) : "";
  getInput("field-bpm").value = metadata.bpm != null ? String(metadata.bpm) : "";
  getInput("field-key").value = metadata.key ?? "";
  getInput("field-comment").value = metadata.comment || url;

  const enrichmentEl = document.getElementById("enrichment-source");
  if (enrichmentEl) {
    enrichmentEl.textContent = source === "claude" ? "Enriched by Claude" : "Metadata preview";
  }
}

function showView(view: "fetch" | "loading" | "preview" | "fetch-error"): void {
  const sections: Record<string, string[]> = {
    "section-fetch": ["fetch"],
    "section-loading": ["loading"],
    "section-preview": ["preview"],
    "section-fetch-error": ["fetch-error"],
  };
  for (const [id, views] of Object.entries(sections)) {
    const el = document.getElementById(id);
    if (el) el.hidden = !views.includes(view);
  }
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

async function handleFetchMetadata(): Promise<void> {
  showView("loading");

  try {
    const preview = await fetchPreview(currentUrl);
    populatePreviewForm(preview.enriched, preview.enrichment_source, currentUrl);
    initialMetadata = { ...preview.enriched };
    previewRaw = preview.raw;
    showView("preview");
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    const errEl = document.getElementById("fetch-error-message");
    if (errEl) errEl.textContent = errMsg;
    showView("fetch-error");
  }
}

async function handleQueueDownload(): Promise<void> {
  const metadata = readMetadataFromForm();
  const format = getSelectedFormat();
  const userEditedFields = computeUserEditedFields(metadata);

  if (previewRaw === null) return;

  const item: QueueItem = {
    id: generateId(),
    url: currentUrl,
    metadata,
    raw: previewRaw,
    format,
    userEditedFields,
    status: "pending",
    addedAt: Date.now(),
  };

  const queue = await readQueue();
  queue.push(item);
  await writeQueue(queue);

  // Reset form state
  initialMetadata = null;
  previewRaw = null;
  showView("fetch");

  // Trigger service worker to process
  void chrome.runtime.sendMessage({ type: "queue_process" });
}

async function init(): Promise<void> {
  initialMetadata = null;
  previewRaw = null;

  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tabs[0]?.url ?? "";

  const isConnected = await healthCheck();
  const statusEl = document.getElementById("server-status");
  if (statusEl) {
    statusEl.className = isConnected ? "status-dot connected" : "status-dot disconnected";
    statusEl.title = isConnected ? "Connected" : "Server not running";
  }

  const fetchBtn = getEl<HTMLButtonElement>("btn-fetch");
  fetchBtn.disabled = !isConnected || !currentUrl;

  showView("fetch");

  // Render existing queue
  const queue = await readQueue();
  renderQueueList(queue);

  // Prune old items beyond 10
  if (queue.length > 10) {
    const sorted = queue.slice().sort((a, b) => b.addedAt - a.addedAt);
    await writeQueue(sorted.slice(0, 10));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  void init();

  getEl<HTMLButtonElement>("btn-fetch").addEventListener("click", () => {
    void handleFetchMetadata();
  });

  getEl<HTMLButtonElement>("btn-queue").addEventListener("click", () => {
    void handleQueueDownload();
  });

  getEl<HTMLButtonElement>("btn-cancel-preview").addEventListener("click", () => {
    showView("fetch");
  });

  getEl<HTMLButtonElement>("btn-retry-fetch").addEventListener("click", () => {
    showView("fetch");
  });

  // Live updates when storage changes
  chrome.storage.onChanged.addListener((changes) => {
    if (changes["queue"]) {
      const newQueue = (changes["queue"].newValue as QueueItem[] | undefined) ?? [];
      renderQueueList(newQueue);
    }
  });
});
