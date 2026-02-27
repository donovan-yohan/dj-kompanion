from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app
from server.downloader import DownloadError
from server.models import EnrichedMetadata, RawMetadata

SAMPLE_RAW = RawMetadata(
    title="DJ Snake - Turn Down for What (Official Video)",
    uploader="DJ Snake",
    duration=210,
    upload_date="20140101",
    description="Turn Down for What",
    tags=["edm", "electronic"],
    source_url="https://www.youtube.com/watch?v=HMUDVMiITOU",
)

SAMPLE_ENRICHED = EnrichedMetadata(
    artist="DJ Snake",
    title="Turn Down for What",
    genre="EDM",
    year=2014,
)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_health(client: AsyncClient) -> None:
    with patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True):
        response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "yt_dlp_version" in data
    assert data["claude_available"] is True


async def test_health_claude_unavailable(client: AsyncClient) -> None:
    with patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False):
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["claude_available"] is False


async def test_preview_success(client: AsyncClient) -> None:
    with (
        patch("server.app.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW),
        patch(
            "server.app.enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
    ):
        response = await client.post(
            "/api/preview", json={"url": "https://www.youtube.com/watch?v=HMUDVMiITOU"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enriched"]["artist"] == "DJ Snake"
    assert data["enriched"]["title"] == "Turn Down for What"
    assert data["enrichment_source"] in ("claude", "none")
    assert "raw" in data


async def test_preview_extraction_error(client: AsyncClient) -> None:
    with patch(
        "server.app.extract_metadata",
        new_callable=AsyncMock,
        side_effect=DownloadError("Not found", url="https://example.com/invalid"),
    ):
        response = await client.post(
            "/api/preview", json={"url": "https://example.com/invalid"}
        )
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "extraction_failed"
    assert "message" in data


async def test_download_success(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {
                    "artist": "DJ Snake",
                    "title": "Turn Down for What",
                },
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["filepath"] == str(mock_path)


async def test_download_failure(client: AsyncClient) -> None:
    with patch(
        "server.app.download_audio",
        new_callable=AsyncMock,
        side_effect=DownloadError("Download failed", url="https://example.com"),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://example.com",
                "metadata": {"artist": "Test", "title": "Track"},
                "format": "best",
            },
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "download_failed"
    assert "message" in data


async def test_download_tagging_failure(client: AsyncClient) -> None:
    from server.tagger import TaggingError

    mock_path = Path("/tmp/download.xyz")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch(
            "server.app.tag_file",
            side_effect=TaggingError("Unsupported format: .xyz", mock_path),
        ),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://example.com",
                "metadata": {"artist": "Test", "title": "Track"},
                "format": "best",
            },
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "tagging_failed"


async def test_cors_chrome_extension(client: AsyncClient) -> None:
    with patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False):
        response = await client.get(
            "/api/health",
            headers={"Origin": "chrome-extension://abcdefghijklmnop"},
        )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "chrome-extension://abcdefghijklmnop"
    )


async def test_preview_missing_url(client: AsyncClient) -> None:
    response = await client.post("/api/preview", json={})
    assert response.status_code == 422
