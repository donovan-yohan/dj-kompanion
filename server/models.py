from __future__ import annotations

from pydantic import BaseModel


class RawMetadata(BaseModel):
    title: str
    uploader: str | None
    duration: int | None
    upload_date: str | None
    description: str | None
    tags: list[str]
    source_url: str


class EnrichedMetadata(BaseModel):
    artist: str
    title: str
    genre: str | None = None
    year: int | None = None
    label: str | None = None
    energy: int | None = None
    bpm: int | None = None
    key: str | None = None
    comment: str = ""


class PreviewResponse(BaseModel):
    raw: RawMetadata
    enriched: EnrichedMetadata
    enrichment_source: str  # "claude" | "none"


class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    format: str = "best"


class DownloadResponse(BaseModel):
    status: str
    filepath: str
