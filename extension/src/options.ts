const DEFAULT_PORT = 9234;
const DEFAULT_HOST = "localhost";

function getEl<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Element #${id} not found`);
  return el as T;
}

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
      showStatus("Settings saved");
    });
  });
});
