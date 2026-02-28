from __future__ import annotations

from pydantic import BaseModel


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


class AnalyzeRequest(BaseModel):
    filepath: str


class AnalyzeResponse(BaseModel):
    status: str
    analysis: AnalysisResult | None = None
    message: str | None = None
