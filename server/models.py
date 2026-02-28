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


class CookieItem(BaseModel):
    domain: str
    name: str
    value: str
    path: str = "/"
    secure: bool = False
    expiration_date: float | None = None


class PreviewRequest(BaseModel):
    url: str
    cookies: list[CookieItem] = []


class PreviewResponse(BaseModel):
    raw: RawMetadata
    enriched: EnrichedMetadata
    enrichment_source: Literal["claude", "none"]


_ALLOWED_FORMATS = {"best", "mp3", "flac", "m4a", "ogg", "opus", "wav", "aac"}
_ENRICHED_FIELDS = frozenset(EnrichedMetadata.model_fields.keys())


class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    raw: RawMetadata
    format: str = "best"
    user_edited_fields: list[str] = []
    cookies: list[CookieItem] = []

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in _ALLOWED_FORMATS:
            msg = f"format must be one of {sorted(_ALLOWED_FORMATS)}"
            raise ValueError(msg)
        return v

    @field_validator("user_edited_fields")
    @classmethod
    def validate_edited_fields(cls, v: list[str]) -> list[str]:
        invalid = set(v) - _ENRICHED_FIELDS
        if invalid:
            msg = f"Unknown metadata fields: {sorted(invalid)}"
            raise ValueError(msg)
        return v


class DownloadResponse(BaseModel):
    status: str
    filepath: str
    enrichment_source: Literal["claude", "basic", "none"] = "none"
    metadata: EnrichedMetadata | None = None


class RetagRequest(BaseModel):
    filepath: str
    metadata: EnrichedMetadata


class RetagResponse(BaseModel):
    status: str
    filepath: str


class HealthResponse(BaseModel):
    status: str
    yt_dlp_version: str
    claude_available: bool


class SegmentInfo(BaseModel):
    label: str
    original_label: str
    start: float
    end: float
    bars: int


class AnalysisResult(BaseModel):
    bpm: float
    key: str
    key_camelot: str
    beats: list[float]
    downbeats: list[float]
    segments: list[SegmentInfo]
    vdj_written: bool = False


class AnalyzeRequest(BaseModel):
    filepath: str


class AnalyzeResponse(BaseModel):
    status: str
    analysis: AnalysisResult
