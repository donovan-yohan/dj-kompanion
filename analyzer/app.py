"""Analyzer microservice — runs the allin1 analysis pipeline in a Docker container."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from analyzer.models import AnalyzeRequest, AnalyzeResponse
from analyzer.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="dj-kompanion-analyzer", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    filepath = Path(req.filepath).resolve()
    audio_root = Path("/audio").resolve()
    if not filepath.is_relative_to(audio_root):
        return AnalyzeResponse(status="error", message="filepath must be under /audio")
    if not filepath.exists():
        return AnalyzeResponse(status="error", message=f"File not found: {req.filepath}")

    try:
        result = await run_pipeline(filepath)
    except Exception:
        logger.error("Analysis failed for %s", req.filepath, exc_info=True)
        return AnalyzeResponse(status="error", message="Analysis pipeline failed")

    return AnalyzeResponse(status="ok", analysis=result)
