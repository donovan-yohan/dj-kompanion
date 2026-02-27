import type { QueueItem } from "./types.js";

export async function readQueue(): Promise<QueueItem[]> {
  const data = await chrome.storage.local.get("queue");
  return (data["queue"] as QueueItem[] | undefined) ?? [];
}

export async function writeQueue(queue: QueueItem[]): Promise<void> {
  await chrome.storage.local.set({ queue });
}
