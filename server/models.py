from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    album: str | None = None
    genre: str | None = None
    year: int | None = None
    label: str | None = None
    energy: int | None = None
    bpm: int | None = None
    key: str | None = None
    cover_art_url: str | None = None
    comment: str = ""


class CookieItem(BaseModel):
    domain: str
    name: str
    value: str
    path: str = "/"
    secure: bool = False
    expiration_date: float | None = None


_ALLOWED_FORMATS = {"best", "mp3", "flac", "m4a", "ogg", "opus", "wav", "aac"}
_ENRICHED_FIELDS = frozenset(EnrichedMetadata.model_fields.keys())


class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    raw: RawMetadata | None = None
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
    enrichment_source: Literal["api+claude", "claude", "basic", "none"] = "none"
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


class PlaylistTrack(BaseModel):
    url: str
    title: str


class ResolvePlaylistRequest(BaseModel):
    url: str
    cookies: list[CookieItem] = []


class ResolvePlaylistResponse(BaseModel):
    playlist_title: str
    tracks: list[PlaylistTrack]


class TrackStatus(BaseModel):
    filepath: str
    status: str
    analysis_path: str | None = None
    error: str | None = None
    analyzed_at: str | None = None


class TracksResponse(BaseModel):
    tracks: list[TrackStatus]


class ReanalyzeRequest(BaseModel):
    filepath: str


class ReanalyzeResponse(BaseModel):
    status: str


class RecommendationSource(StrEnum):
    musicbrainz = "musicbrainz"
    listenbrainz = "listenbrainz"
    acousticbrainz = "acousticbrainz"


class CamelotPolicy(StrEnum):
    same = "same"
    adjacent = "adjacent"
    energy_safe = "energy_safe"


class CompatibilityStatus(StrEnum):
    candidate_unvalidated = "candidate_unvalidated"
    locally_validated_match = "locally_validated_match"
    locally_validated_mismatch = "locally_validated_mismatch"
    local_analysis_missing = "local_analysis_missing"


class RecommendedDownloadFilters(BaseModel):
    genres: list[str] | None = None
    bpm_tolerance: float = Field(default=4.0, ge=0, le=20)
    camelot_policy: CamelotPolicy = CamelotPolicy.adjacent
    exclude_existing: bool = True
    include_low_confidence: bool = False


class RecommendedDownloadsRequest(BaseModel):
    seed_filepath: str | None = None
    seed_filepaths: list[str] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    filters: RecommendedDownloadFilters = Field(default_factory=RecommendedDownloadFilters)
    sources: list[RecommendationSource] = Field(
        default_factory=lambda: [
            RecommendationSource.musicbrainz,
            RecommendationSource.listenbrainz,
            RecommendationSource.acousticbrainz,
        ]
    )

    @model_validator(mode="after")
    def require_seed(self) -> RecommendedDownloadsRequest:
        if self.seed_filepath:
            return self
        if self.seed_filepaths:
            self.seed_filepaths = [p for p in self.seed_filepaths if p]
            if self.seed_filepaths:
                return self
        raise ValueError("seed_filepath or non-empty seed_filepaths is required")


class RecommendationSeed(BaseModel):
    filepath: str
    bpm: float | None = None
    key: str | None = None
    key_camelot: str | None = None
    status: Literal["analyzed", "required"]


class ProviderSignals(BaseModel):
    sources: list[RecommendationSource]
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    bpm: float | None = None
    key: str | None = None
    key_camelot: str | None = None


class ScoreBreakdown(BaseModel):
    source_confidence: float
    metadata_similarity: float
    genre_tag_overlap: float
    bpm_hint: float
    camelot_hint: float
    dedupe_penalty: float


class RecommendationCompatibilityPredicted(BaseModel):
    bpm_delta: float | None = None
    camelot_relation: str | None = None


class RecommendationCompatibilityFinal(BaseModel):
    bpm: float | None = None
    key_camelot: str | None = None
    compatible: bool | None = None


class RecommendationCompatibility(BaseModel):
    status: CompatibilityStatus
    reason: str
    predicted: RecommendationCompatibilityPredicted
    final: RecommendationCompatibilityFinal


class RecommendationActions(BaseModel):
    search_query: str
    musicbrainz_url: str | None = None


class RecommendedDownload(BaseModel):
    candidate_id: str
    artist: str
    title: str
    recording_mbid: str | None = None
    release_mbid: str | None = None
    source_urls: dict[str, str] = Field(default_factory=dict)
    provider_signals: ProviderSignals
    score: float
    score_breakdown: ScoreBreakdown
    compatibility: RecommendationCompatibility
    actions: RecommendationActions


class ProviderError(BaseModel):
    source: RecommendationSource
    error: str
    retryable: bool = True


class RecommendedDownloadsResponse(BaseModel):
    seed: RecommendationSeed
    recommendations: list[RecommendedDownload]
    sources_used: list[RecommendationSource]
    provider_errors: list[ProviderError]
    warnings: list[str]
