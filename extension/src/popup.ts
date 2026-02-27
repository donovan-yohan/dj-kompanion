import { fetchPreview, healthCheck, requestDownload } from "./api.js";
import { getEl } from "./dom.js";
import type { DownloadRequest, EnrichedMetadata, RawMetadata } from "./types.js";

type PopupState = "initial" | "loading" | "preview" | "downloading" | "complete" | "error";

let currentUrl = "";
let lastErrorMessage = "";
let initialMetadata: EnrichedMetadata | null = null;
let previewRaw: RawMetadata | null = null;

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
    year: getInput("field-year").value !== "" ? parseInt(getInput("field-year").value, 10) : null,
    label: getInput("field-label").value || null,
    energy:
      getInput("field-energy").value !== ""
        ? parseInt(getInput("field-energy").value, 10)
        : null,
    bpm:
      getInput("field-bpm").value !== "" ? parseFloat(getInput("field-bpm").value) : null,
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
    enrichmentEl.textContent =
      source === "claude" ? "Enriched by Claude" : "Metadata preview";
  }
}

function setBadge(text: string, color: string): void {
  void chrome.action.setBadgeText({ text });
  void chrome.action.setBadgeBackgroundColor({ color });
}

function clearBadge(): void {
  void chrome.action.setBadgeText({ text: "" });
}

async function init(): Promise<void> {
  initialMetadata = null;
  previewRaw = null;

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
  if (!currentUrl) {
    fetchBtn.disabled = true;
    const urlDisplay2 = document.getElementById("current-url");
    if (urlDisplay2) urlDisplay2.textContent = "(no URL — open a web page first)";
  } else {
    fetchBtn.disabled = !isConnected;
  }

  render("initial");
}

async function handleFetchMetadata(): Promise<void> {
  const btn = getEl<HTMLButtonElement>("btn-fetch");
  btn.disabled = true;
  render("loading");

  try {
    const preview = await fetchPreview(currentUrl);
    populatePreviewForm(preview.enriched, preview.enrichment_source, currentUrl);
    initialMetadata = { ...preview.enriched };
    previewRaw = preview.raw;
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
  const userEditedFields = computeUserEditedFields(metadata);

  if (previewRaw === null) {
    lastErrorMessage = "Preview data missing. Please fetch metadata first.";
    const errEl = document.getElementById("error-message");
    if (errEl) errEl.textContent = lastErrorMessage;
    render("error");
    return;
  }

  const req: DownloadRequest = {
    url: currentUrl,
    metadata,
    raw: previewRaw,
    format,
    user_edited_fields: userEditedFields,
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
