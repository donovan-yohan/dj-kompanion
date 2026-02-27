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

export interface DownloadRequest {
  url: string;
  metadata: EnrichedMetadata;
  format: string;
}

export interface DownloadResponse {
  status: string;
  filepath: string;
}
