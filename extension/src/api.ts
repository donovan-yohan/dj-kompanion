import { DEFAULT_HOST, DEFAULT_PORT } from "./constants.js";
import type { DownloadRequest, DownloadResponse, PreviewResponse, RetagRequest, RetagResponse } from "./types.js";

export async function getBaseUrl(): Promise<string> {
  return new Promise((resolve, reject) => {
    chrome.storage.sync.get({ port: DEFAULT_PORT, host: DEFAULT_HOST }, (items) => {
      if (chrome.runtime.lastError) {
        reject(new Error(`Failed to read settings: ${chrome.runtime.lastError.message}`));
        return;
      }
      resolve(`http://${items["host"] as string}:${items["port"] as number}`);
    });
  });
}

export async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    clearTimeout(timer);
    return response;
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

export async function healthCheck(): Promise<boolean> {
  try {
    const baseUrl = await getBaseUrl();
    const response = await fetchWithTimeout(`${baseUrl}/api/health`, {}, 5000);
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchPreview(url: string): Promise<PreviewResponse> {
  const baseUrl = await getBaseUrl();
  const response = await fetchWithTimeout(
    `${baseUrl}/api/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    },
    10000,
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as PreviewResponse;
}

export async function requestDownload(req: DownloadRequest): Promise<DownloadResponse> {
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
  return (await response.json()) as DownloadResponse;
}

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
