import { DEFAULT_HOST, DEFAULT_PORT } from "./constants.js";
import { getEl } from "./dom.js";

function showStatus(message: string, isError = false): void {
  const status = getEl<HTMLParagraphElement>("status");
  status.textContent = message;
  status.className = isError ? "error" : "success";
  setTimeout(() => {
    status.textContent = "";
    status.className = "";
  }, 3000);
}

document.addEventListener("DOMContentLoaded", () => {
  const portInput = getEl<HTMLInputElement>("port");
  const hostInput = getEl<HTMLInputElement>("host");
  const form = getEl<HTMLFormElement>("options-form");

  chrome.storage.sync.get({ port: DEFAULT_PORT, host: DEFAULT_HOST }, (items) => {
    if (chrome.runtime.lastError) {
      showStatus(`Failed to load settings: ${chrome.runtime.lastError.message}`, true);
      return;
    }
    portInput.value = String(items["port"] as number);
    hostInput.value = items["host"] as string;
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const port = parseInt(portInput.value, 10);
    const host = hostInput.value.trim();

    if (isNaN(port) || port < 1 || port > 65535) {
      showStatus("Port must be between 1 and 65535", true);
      return;
    }
    if (!host) {
      showStatus("Host cannot be empty", true);
      return;
    }

    chrome.storage.sync.set({ port, host }, () => {
      if (chrome.runtime.lastError) {
        showStatus(`Failed to save: ${chrome.runtime.lastError.message}`, true);
        return;
      }
      showStatus("Settings saved");
    });
  });
});
