import { fetchPreview, healthCheck, requestDownload } from "./api.js";
import type { DownloadRequest, EnrichedMetadata } from "./types.js";

type PopupState = "initial" | "loading" | "preview" | "downloading" | "complete" | "error";

let currentUrl = "";
let lastErrorMessage = "";

function getEl<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Element #${id} not found`);
  return el as T;
}

function getInput(id: string): HTMLInputElement {
  return getEl<HTMLInputElement>(id);
}

function render(state: PopupState): void {
  const sections: Record<string, PopupState[]> = {
    "section-initial": ["initial"],
    "section-loading": ["loading"],
    "section-preview": ["preview"],
    "section-downloading": ["downloading"],
    "section-complete": ["complete"],
    "section-error": ["error"],
  };

  for (const [id, states] of Object.entries(sections)) {
    const el = document.getElementById(id);
    if (el) {
      el.hidden = !states.includes(state);
    }
  }
}

function readMetadataFromForm(): EnrichedMetadata {
  return {
    artist: getInput("field-artist").value,
    title: getInput("field-title").value,
    genre: getInput("field-genre").value || null,
    year: parseInt(getInput("field-year").value, 10) || null,
    label: getInput("field-label").value || null,
    energy: parseInt(getInput("field-energy").value, 10) || null,
    bpm: parseFloat(getInput("field-bpm").value) || null,
    key: getInput("field-key").value || null,
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
    enrichmentEl.textContent =
      source === "claude" ? "Enriched by Claude" : "Basic parsing";
  }
}

function setBadge(text: string, color: string): void {
  chrome.runtime.sendMessage({ type: "badge_set", text, color });
}

function clearBadge(): void {
  chrome.runtime.sendMessage({ type: "badge_clear" });
}

async function init(): Promise<void> {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  currentUrl = tab?.url ?? "";

  const urlDisplay = document.getElementById("current-url");
  if (urlDisplay) {
    urlDisplay.textContent = currentUrl || "(no URL)";
  }

  const isConnected = await healthCheck();
  const statusEl = document.getElementById("server-status");
  if (statusEl) {
    if (isConnected) {
      statusEl.textContent = "Connected to local server";
      statusEl.className = "status connected";
    } else {
      statusEl.textContent = "Server not running";
      statusEl.className = "status disconnected";
    }
  }

  const fetchBtn = getEl<HTMLButtonElement>("btn-fetch");
  fetchBtn.disabled = !isConnected;

  render("initial");
}

async function handleFetchMetadata(): Promise<void> {
  render("loading");

  try {
    const preview = await fetchPreview(currentUrl);
    populatePreviewForm(preview.enriched, preview.enrichment_source, currentUrl);
    render("preview");
  } catch (err) {
    lastErrorMessage = err instanceof Error ? err.message : String(err);
    const errEl = document.getElementById("error-message");
    if (errEl) errEl.textContent = lastErrorMessage;
    render("error");
  }
}

async function handleDownload(): Promise<void> {
  const metadata = readMetadataFromForm();
  const format = getSelectedFormat();

  const req: DownloadRequest = {
    url: currentUrl,
    metadata,
    format,
  };

  render("downloading");
  setBadge("...", "#888888");

  try {
    const result = await requestDownload(req);

    const completeTitleEl = document.getElementById("complete-title");
    if (completeTitleEl) {
      completeTitleEl.textContent = `${metadata.artist} - ${metadata.title}`;
    }
    const completePathEl = document.getElementById("complete-path");
    if (completePathEl) {
      completePathEl.textContent = `→ ${result.filepath}`;
    }

    clearBadge();
    render("complete");
  } catch (err) {
    lastErrorMessage = err instanceof Error ? err.message : String(err);
    const errEl = document.getElementById("error-message");
    if (errEl) errEl.textContent = lastErrorMessage;
    clearBadge();
    render("error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  void init();

  getEl<HTMLButtonElement>("btn-fetch").addEventListener("click", () => {
    void handleFetchMetadata();
  });

  getEl<HTMLButtonElement>("btn-download").addEventListener("click", () => {
    void handleDownload();
  });

  getEl<HTMLButtonElement>("btn-retry").addEventListener("click", () => {
    render("initial");
    void init();
  });

  getEl<HTMLButtonElement>("btn-another").addEventListener("click", () => {
    render("initial");
    void init();
  });
});
