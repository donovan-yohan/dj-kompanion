from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app
from server.models import (
    CompatibilityStatus,
    ProviderSignals,
    RecommendationActions,
    RecommendationCompatibility,
    RecommendationCompatibilityFinal,
    RecommendationCompatibilityPredicted,
    RecommendationSeed,
    RecommendationSource,
    RecommendedDownload,
    RecommendedDownloadsResponse,
    ScoreBreakdown,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class FakeRecommendationService:
    def __init__(self) -> None:
        self.called = False
        self.request_sources: list[RecommendationSource] = []

    def recommend(self, request):  # type: ignore[no-untyped-def]
        self.called = True
        self.request_sources = request.sources
        return RecommendedDownloadsResponse(
            seed=RecommendationSeed(
                filepath=request.seed_filepath or request.seed_filepaths[0],
                bpm=128,
                key="A minor",
                key_camelot="8A",
                status="analyzed",
            ),
            recommendations=[
                RecommendedDownload(
                    candidate_id="mbid:abc",
                    artist="Candidate Artist",
                    title="Candidate Title",
                    recording_mbid="abc",
                    release_mbid=None,
                    source_urls={"musicbrainz": "https://musicbrainz.org/recording/abc"},
                    provider_signals=ProviderSignals(
                        sources=[RecommendationSource.musicbrainz],
                        genres=["house"],
                        bpm=129,
                        key_camelot="9A",
                    ),
                    score=0.75,
                    score_breakdown=ScoreBreakdown(
                        source_confidence=1,
                        metadata_similarity=0.8,
                        genre_tag_overlap=0.5,
                        bpm_hint=0.375,
                        camelot_hint=0.4,
                        dedupe_penalty=0,
                    ),
                    compatibility=RecommendationCompatibility(
                        status=CompatibilityStatus.candidate_unvalidated,
                        reason="remote candidate has not been downloaded/analyzed locally",
                        predicted=RecommendationCompatibilityPredicted(bpm_delta=1, camelot_relation="adjacent"),
                        final=RecommendationCompatibilityFinal(),
                    ),
                    actions=RecommendationActions(search_query="Candidate Artist Candidate Title"),
                )
            ],
            sources_used=[RecommendationSource.musicbrainz],
            provider_errors=[],
            warnings=[],
        )


async def test_request_requires_seed(client: AsyncClient) -> None:
    response = await client.post("/api/recommended-downloads", json={})

    assert response.status_code == 422


async def test_rejects_spotify_source(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeRecommendationService()
    monkeypatch.setattr("server.app.get_recommendation_service", lambda: service)

    response = await client.post(
        "/api/recommended-downloads",
        json={"seed_filepath": "/music/seed.m4a", "sources": ["spotify"]},
    )

    assert response.status_code == 422
    assert service.called is False


async def test_endpoint_returns_service_response(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeRecommendationService()
    monkeypatch.setattr("server.app.get_recommendation_service", lambda: service)

    response = await client.post(
        "/api/recommended-downloads",
        json={"seed_filepath": "/music/seed.m4a", "limit": 5, "sources": ["musicbrainz"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["seed"]["filepath"] == "/music/seed.m4a"
    assert data["recommendations"][0]["candidate_id"] == "mbid:abc"
    assert data["recommendations"][0]["compatibility"]["status"] == "candidate_unvalidated"
    assert service.request_sources == [RecommendationSource.musicbrainz]


async def test_missing_seed_returns_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.recommendations.service import SeedNotFoundError

    class MissingSeedService:
        def recommend(self, request):  # type: ignore[no-untyped-def]
            raise SeedNotFoundError(Path(request.seed_filepath or ""))

    monkeypatch.setattr("server.app.get_recommendation_service", lambda: MissingSeedService())

    response = await client.post(
        "/api/recommended-downloads",
        json={"seed_filepath": "/missing.m4a"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "seed_not_found"


async def test_unanalyzed_seed_returns_409(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.recommendations.service import SeedAnalysisRequiredError

    class UnanalyzedSeedService:
        def recommend(self, request):  # type: ignore[no-untyped-def]
            raise SeedAnalysisRequiredError(Path(request.seed_filepath or ""))

    monkeypatch.setattr("server.app.get_recommendation_service", lambda: UnanalyzedSeedService())

    response = await client.post(
        "/api/recommended-downloads",
        json={"seed_filepath": "/unanalyzed.m4a"},
    )

    assert response.status_code == 409
    data = response.json()
    assert data["error"] == "seed_analysis_required"
    assert data["seed"]["status"] == "required"
