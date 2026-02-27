import type { DownloadRequest, DownloadResponse, PreviewResponse } from "./types.js";

const DEFAULT_PORT = 9234;
const DEFAULT_HOST = "localhost";

async function getBaseUrl(): Promise<string> {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ port: DEFAULT_PORT, host: DEFAULT_HOST }, (items) => {
      resolve(`http://${items["host"] as string}:${items["port"] as number}`);
    });
  });
}

export async function healthCheck(): Promise<boolean> {
  try {
    const baseUrl = await getBaseUrl();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(`${baseUrl}/api/health`, { signal: controller.signal });
    clearTimeout(timer);
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchPreview(url: string): Promise<PreviewResponse> {
  const baseUrl = await getBaseUrl();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(
      `${baseUrl}/api/preview?url=${encodeURIComponent(url)}`,
      { signal: controller.signal },
    );
    clearTimeout(timer);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Server error ${response.status}: ${text}`);
    }
    return (await response.json()) as PreviewResponse;
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

export async function requestDownload(req: DownloadRequest): Promise<DownloadResponse> {
  const baseUrl = await getBaseUrl();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(`${baseUrl}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Server error ${response.status}: ${text}`);
    }
    return (await response.json()) as DownloadResponse;
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}
