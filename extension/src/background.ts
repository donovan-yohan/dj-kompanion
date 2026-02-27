import { getBaseUrl, fetchWithTimeout } from "./api.js";
import type { QueueItem, DownloadRequest, DownloadResponse } from "./types.js";

// --- Queue storage helpers ---

async function readQueue(): Promise<QueueItem[]> {
  const data = await chrome.storage.local.get("queue");
  return (data["queue"] as QueueItem[] | undefined) ?? [];
}

async function writeQueue(queue: QueueItem[]): Promise<void> {
  await chrome.storage.local.set({ queue });
}

async function updateItem(id: string, updates: Partial<QueueItem>): Promise<void> {
  const queue = await readQueue();
  const idx = queue.findIndex((item) => item.id === id);
  if (idx !== -1) {
    queue[idx] = { ...queue[idx], ...updates };
    await writeQueue(queue);
  }
}

// --- Badge ---

async function updateBadge(): Promise<void> {
  const queue = await readQueue();
  const active = queue.filter(
    (i) => i.status === "pending" || i.status === "downloading",
  ).length;
  if (active > 0) {
    await chrome.action.setBadgeText({ text: String(active) });
    await chrome.action.setBadgeBackgroundColor({ color: "#3b82f6" });
  } else {
    await chrome.action.setBadgeText({ text: "" });
  }
}

// --- Processing loop ---

let processing = false;

async function processQueue(): Promise<void> {
  if (processing) return;
  processing = true;

  try {
    while (true) {
      const queue = await readQueue();
      const pending = queue.find((item) => item.status === "pending");
      if (!pending) break;

      await updateItem(pending.id, { status: "downloading" });
      await updateBadge();

      try {
        const req: DownloadRequest = {
          url: pending.url,
          metadata: pending.metadata,
          raw: pending.raw,
          format: pending.format,
          user_edited_fields: pending.userEditedFields,
        };

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

        const result = (await response.json()) as DownloadResponse;
        await updateItem(pending.id, {
          status: "complete",
          filepath: result.filepath,
          enrichmentSource: result.enrichment_source,
          metadata: result.metadata ?? pending.metadata,
        });
      } catch (err) {
        await updateItem(pending.id, {
          status: "error",
          error: err instanceof Error ? err.message : String(err),
        });
      }

      await updateBadge();
    }
  } finally {
    processing = false;
    await updateBadge();
  }
}

// --- Message listener ---

type ServiceWorkerMessage = { type: "queue_process" };

chrome.runtime.onMessage.addListener((message: ServiceWorkerMessage) => {
  if (message.type === "queue_process") {
    void processQueue();
  }
});

// --- Stale recovery on startup ---

chrome.runtime.onStartup.addListener(() => {
  void (async () => {
    const queue = await readQueue();
    let changed = false;
    for (const item of queue) {
      if (item.status === "downloading") {
        item.status = "pending";
        changed = true;
      }
    }
    if (changed) {
      await writeQueue(queue);
      void processQueue();
    }
    await updateBadge();
  })();
});
