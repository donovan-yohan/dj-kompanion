from __future__ import annotations

import httpx

from server.models import RecommendationSource, RecommendedDownloadFilters
from server.recommendations.open_data_clients import AcousticBrainzClient, MusicBrainzClient
from server.recommendations.providers import AcousticBrainzProvider, ProviderSeed


def test_musicbrainz_client_sends_user_agent() -> None:
    seen_user_agent = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_user_agent
        seen_user_agent = request.headers["user-agent"]
        return httpx.Response(200, json={"recordings": []})

    client = MusicBrainzClient(
        user_agent="dj-kompanion-test/1.0 contact@example.com",
        transport=httpx.MockTransport(handler),
    )

    client.search_recordings("Artist", "Title")

    assert seen_user_agent == "dj-kompanion-test/1.0 contact@example.com"


def test_acousticbrainz_404_is_non_blocking() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    provider = AcousticBrainzProvider(
        AcousticBrainzClient(transport=httpx.MockTransport(handler))
    )

    result = provider.fetch(
        ProviderSeed(
            filepath="/music/Artist - Title.m4a",
            artist="Artist",
            title="Title",
            recording_mbid="missing-mbid",
        ),
        RecommendedDownloadFilters(),
        limit=10,
    )

    assert result.candidates == []
    assert result.errors == []


def test_acousticbrainz_provider_returns_low_confidence_hint_candidate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/count"):
            return httpx.Response(200, json={"count": 1})
        if request.url.path.endswith("/low-level"):
            return httpx.Response(
                200,
                json={
                    "rhythm": {"bpm": 127.7},
                    "tonal": {"key_key": "A", "key_scale": "minor"},
                },
            )
        return httpx.Response(
            200,
            json={"genre_dortmund": {"value": "electronic"}},
        )

    provider = AcousticBrainzProvider(
        AcousticBrainzClient(transport=httpx.MockTransport(handler))
    )

    result = provider.fetch(
        ProviderSeed(
            filepath="/music/Artist - Title.m4a",
            artist="Artist",
            title="Title",
            recording_mbid="mbid-1",
        ),
        RecommendedDownloadFilters(),
        limit=10,
    )

    assert result.errors == []
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.source == RecommendationSource.acousticbrainz
    assert candidate.bpm == 127.7
    assert candidate.key == "A minor"
    assert candidate.recording_mbid == "mbid-1"
    assert candidate.source_confidence == 0.25
