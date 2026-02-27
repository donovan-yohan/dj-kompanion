import { DEFAULT_HOST, DEFAULT_PORT } from "./constants.js";
import type {
  AnalyzeResponse,
  CookieData,
  PreviewResponse,
  RetagRequest,
  RetagResponse,
} from "./types.js";

export async function getYouTubeCookies(): Promise<CookieData[]> {
  try {
    const cookies = await chrome.cookies.getAll({ domain: ".youtube.com" });
    return cookies.map((c) => ({
      domain: c.domain,
      name: c.name,
      value: c.value,
      path: c.path,
      secure: c.secure,
      expiration_date: c.expirationDate ?? null,
    }));
  } catch {
    return [];
  }
}

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
  timeoutMs: number
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
  const cookies = await getYouTubeCookies();
  const response = await fetchWithTimeout(
    `${baseUrl}/api/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookies }),
    },
    10000
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as PreviewResponse;
}

export async function requestAnalyze(filepath: string): Promise<AnalyzeResponse> {
  const baseUrl = await getBaseUrl();
  const response = await fetchWithTimeout(
    `${baseUrl}/api/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filepath }),
    },
    300000 // 5 minute timeout — ML analysis is slow
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as AnalyzeResponse;
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
    30000
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server error ${response.status}: ${text}`);
  }
  return (await response.json()) as RetagResponse;
}
