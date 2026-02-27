from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


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


class PreviewRequest(BaseModel):
    url: str


class PreviewResponse(BaseModel):
    raw: RawMetadata
    enriched: EnrichedMetadata
    enrichment_source: Literal["claude", "none"]


_ALLOWED_FORMATS = {"best", "mp3", "flac", "m4a", "ogg", "opus", "wav", "aac"}


class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    format: str = "best"

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in _ALLOWED_FORMATS:
            msg = f"format must be one of {sorted(_ALLOWED_FORMATS)}"
            raise ValueError(msg)
        return v


class DownloadResponse(BaseModel):
    status: str
    filepath: str


class HealthResponse(BaseModel):
    status: str
    yt_dlp_version: str
    claude_available: bool
