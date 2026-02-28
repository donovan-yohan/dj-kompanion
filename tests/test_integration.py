"""Integration tests for the download flow with metadata API enrichment.

Scenarios NOT already covered by test_app.py:
- API succeeds but Claude fails → enrichment_source: "basic"
- metadata_lookup disabled → search_metadata not called, Claude enriches → enrichment_source: "claude"

Already covered by test_app.py (not duplicated here):
- API+Claude happy path → enrichment_source: "api+claude"
- API returns empty (fails/down), Claude succeeds → enrichment_source: "claude"
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from server.app import app
from server.config import AppConfig, LLMConfig, MetadataLookupConfig
from server.metadata_lookup import MetadataCandidate
from server.models import EnrichedMetadata

SAMPLE_RAW_DICT: dict[str, object] = {
    "title": "Peggy Gou - (It Goes Like) Nanana",
    "uploader": "Peggy Gou",
    "duration": 195,
    "upload_date": "20230101",
    "description": "Nanana",
    "tags": ["house", "electronic"],
    "source_url": "https://www.youtube.com/watch?v=example",
}

SAMPLE_CANDIDATES = [
    MetadataCandidate(
        source="musicbrainz",
        artist="Peggy Gou",
        title="(It Goes Like) Nanana",
        album="(It Goes Like) Nanana",
        genre_tags=["house"],
        year=2023,
    )
]


def _make_config(*, metadata_lookup_enabled: bool = True) -> AppConfig:
    """Build an AppConfig with LLM enabled and configurable metadata_lookup."""
    return AppConfig(
        llm=LLMConfig(enabled=True, model="haiku"),
        metadata_lookup=MetadataLookupConfig(enabled=metadata_lookup_enabled),
    )


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_api_succeeds_claude_fails_falls_back_to_basic(client: AsyncClient) -> None:
    """When API returns candidates but Claude times out/fails, fall back to basic enrichment."""
    mock_path = Path("/tmp/Peggy Gou - Nanana.m4a")
    cfg = _make_config(metadata_lookup_enabled=True)

    with (
        patch("server.app.load_config", return_value=cfg),
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch(
            "server.app.search_metadata",
            new_callable=AsyncMock,
            return_value=SAMPLE_CANDIDATES,
        ),
        # Claude fails — try_enrich_metadata returns None
        patch("server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=example",
                "metadata": {"artist": "Peggy Gou", "title": "(It Goes Like) Nanana"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )

    assert response.status_code == 200
    data = response.json()
    # API had candidates but Claude failed → must NOT use api+claude or auto-pick; use basic
    assert data["enrichment_source"] == "basic"


async def test_metadata_lookup_disabled_claude_enriches_without_candidates(
    client: AsyncClient,
) -> None:
    """When metadata_lookup is disabled, search_metadata is never called and Claude enriches
    using only raw metadata (no candidates), resulting in enrichment_source: "claude"."""
    mock_path = Path("/tmp/Peggy Gou - Nanana.m4a")
    cfg = _make_config(metadata_lookup_enabled=False)
    mock_enriched = EnrichedMetadata(
        artist="Peggy Gou",
        title="(It Goes Like) Nanana",
        genre="House",
        year=2023,
    )
    mock_search = AsyncMock()

    with (
        patch("server.app.load_config", return_value=cfg),
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.search_metadata", mock_search),
        patch(
            "server.app.try_enrich_metadata",
            new_callable=AsyncMock,
            return_value=mock_enriched,
        ),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=example",
                "metadata": {"artist": "Peggy Gou", "title": "(It Goes Like) Nanana"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )

    assert response.status_code == 200
    data = response.json()
    # Claude enriched without API candidates
    assert data["enrichment_source"] == "claude"
    # search_metadata must not have been called (metadata_lookup disabled)
    mock_search.assert_not_called()
