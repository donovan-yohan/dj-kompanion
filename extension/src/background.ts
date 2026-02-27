import { fetchWithTimeout, getBaseUrl, getYouTubeCookies, requestAnalyze } from "./api.js";
import { readQueue, writeQueue } from "./queue-storage.js";
import type { DownloadRequest, DownloadResponse, QueueItem } from "./types.js";

async function updateItem(id: string, updates: Partial<QueueItem>): Promise<void> {
  const queue = await readQueue();
  const idx = queue.findIndex((item) => item.id === id);
  if (idx !== -1) {
    queue[idx] = { ...queue[idx], ...updates };
    await writeQueue(queue);
  }
}

async function updateBadge(): Promise<void> {
  const queue = await readQueue();
  const active = queue.filter(
    (i) => i.status === "pending" || i.status === "downloading" || i.status === "analyzing"
  ).length;
  if (active > 0) {
    await chrome.action.setBadgeText({ text: String(active) });
    await chrome.action.setBadgeBackgroundColor({ color: "#3b82f6" });
  } else {
    await chrome.action.setBadgeText({ text: "" });
  }
}

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
        const cookies = await getYouTubeCookies();
        const req: DownloadRequest = {
          url: pending.url,
          metadata: pending.metadata,
          raw: pending.raw,
          format: pending.format,
          user_edited_fields: pending.userEditedFields,
          cookies,
        };

        const baseUrl = await getBaseUrl();
        const response = await fetchWithTimeout(
          `${baseUrl}/api/download`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(req),
          },
          120000
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

        // Trigger analysis (non-critical — failure keeps status as "complete")
        await updateItem(pending.id, { status: "analyzing" });
        await updateBadge();
        try {
          const analyzeResult = await requestAnalyze(result.filepath);
          await updateItem(pending.id, { status: "analyzed", analysis: analyzeResult.analysis });
        } catch (analyzeErr) {
          console.warn("Analysis failed (non-critical):", analyzeErr);
          await updateItem(pending.id, { status: "complete" });
        }
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

type ServiceWorkerMessage = { type: "queue_process" };

chrome.runtime.onMessage.addListener((message: ServiceWorkerMessage) => {
  if (message.type === "queue_process") {
    void processQueue();
  }
});

chrome.runtime.onStartup.addListener(() => {
  void (async () => {
    const queue = await readQueue();
    let changed = false;
    for (const item of queue) {
      if (item.status === "downloading") {
        item.status = "pending";
        changed = true;
      } else if (item.status === "analyzing") {
        // Download already succeeded — reset to complete, not pending
        item.status = "complete";
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
