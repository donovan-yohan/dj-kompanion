export interface RawMetadata {
  title: string;
  uploader: string | null;
  duration: number | null;
  upload_date: string | null;
  description: string | null;
  tags: string[];
  source_url: string;
}

export interface EnrichedMetadata {
  artist: string;
  title: string;
  genre: string | null;
  year: number | null;
  label: string | null;
  energy: number | null;
  bpm: number | null;
  key: string | null;
  comment: string;
}

export interface PreviewResponse {
  raw: RawMetadata;
  enriched: EnrichedMetadata;
  enrichment_source: "claude" | "none";
}

export interface CookieData {
  domain: string;
  name: string;
  value: string;
  path: string;
  secure: boolean;
  expiration_date: number | null;
}

export interface DownloadRequest {
  url: string;
  metadata: EnrichedMetadata;
  raw: RawMetadata;
  format: string;
  user_edited_fields: string[];
  cookies?: CookieData[];
}

export interface DownloadResponse {
  status: string;
  filepath: string;
  enrichment_source: "claude" | "basic" | "none";
  metadata?: EnrichedMetadata;
}

export interface QueueItem {
  id: string;
  url: string;
  metadata: EnrichedMetadata;
  raw: RawMetadata;
  format: string;
  userEditedFields: string[];
  status: "pending" | "downloading" | "complete" | "error";
  enrichmentSource?: "claude" | "basic" | "none";
  filepath?: string;
  error?: string;
  addedAt: number;
}

export interface RetagRequest {
  filepath: string;
  metadata: EnrichedMetadata;
}

export interface RetagResponse {
  status: string;
  filepath: string;
}
