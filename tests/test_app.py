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
from server.models import AnalysisResult, EnrichedMetadata, RawMetadata, SegmentInfo

SAMPLE_RAW = RawMetadata(
    title="DJ Snake - Turn Down for What (Official Video)",
    uploader="DJ Snake",
    duration=210,
    upload_date="20140101",
    description="Turn Down for What",
    tags=["edm", "electronic"],
    source_url="https://www.youtube.com/watch?v=HMUDVMiITOU",
)

SAMPLE_RAW_DICT: dict[str, object] = {
    "title": "DJ Snake - Turn Down for What (Official Video)",
    "uploader": "DJ Snake",
    "duration": 210,
    "upload_date": "20140101",
    "description": "Turn Down for What",
    "tags": ["edm", "electronic"],
    "source_url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
}

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
    with patch("server.app.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW):
        response = await client.post(
            "/api/preview", json={"url": "https://www.youtube.com/watch?v=HMUDVMiITOU"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enriched"]["artist"] == "DJ Snake"
    assert data["enrichment_source"] == "none"
    assert "raw" in data


async def test_preview_extraction_error(client: AsyncClient) -> None:
    with patch(
        "server.app.extract_metadata",
        new_callable=AsyncMock,
        side_effect=DownloadError("Not found", url="https://example.com/invalid"),
    ):
        response = await client.post("/api/preview", json={"url": "https://example.com/invalid"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "extraction_failed"
    assert "message" in data


async def test_download_success(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["filepath"] == str(mock_path)
    assert data["enrichment_source"] == "none"


async def test_download_failure(client: AsyncClient) -> None:
    with (
        patch(
            "server.app.download_audio",
            new_callable=AsyncMock,
            side_effect=DownloadError("Download failed", url="https://example.com"),
        ),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://example.com",
                "metadata": {"artist": "Test", "title": "Track"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "download_failed"


async def test_download_tagging_failure(client: AsyncClient) -> None:
    from server.tagger import TaggingError

    mock_path = Path("/tmp/download.xyz")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch(
            "server.app.tag_file",
            side_effect=TaggingError("Unsupported format: .xyz", mock_path),
        ),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://example.com",
                "metadata": {"artist": "Test", "title": "Track"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "tagging_failed"


async def test_download_with_claude_enrichment(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch(
            "server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enrichment_source"] == "claude"


async def test_download_claude_fails_gracefully(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["enrichment_source"] == "basic"


async def test_download_user_edited_fields_preserved(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    claude_enriched = EnrichedMetadata(
        artist="Claude Artist", title="Claude Title", genre="EDM", year=2014
    )
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path) as mock_tag,
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch(
            "server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=claude_enriched
        ),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "My Artist", "title": "My Title"},
                "raw": SAMPLE_RAW_DICT,
                "format": "best",
                "user_edited_fields": ["artist", "title"],
            },
        )
    assert response.status_code == 200
    # Verify tag_file was called with merged metadata preserving user edits
    tagged_metadata = mock_tag.call_args[0][1]
    assert tagged_metadata.artist == "My Artist"  # user edited, preserved
    assert tagged_metadata.title == "My Title"  # user edited, preserved
    assert tagged_metadata.genre == "EDM"  # not edited, Claude fills in
    assert tagged_metadata.year == 2014  # not edited, Claude fills in


async def test_cors_chrome_extension(client: AsyncClient) -> None:
    with patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False):
        response = await client.get(
            "/api/health",
            headers={"Origin": "chrome-extension://abcdefghijklmnop"},
        )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "chrome-extension://abcdefghijklmnop"
    )


async def test_preview_missing_url(client: AsyncClient) -> None:
    response = await client.post("/api/preview", json={})
    assert response.status_code == 422


SAMPLE_ENRICHED_DICT: dict[str, object] = {
    "artist": "DJ Snake",
    "title": "Turn Down for What",
    "genre": "EDM",
    "year": 2014,
}


async def test_retag_success(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.Path") as mock_filepath_cls,
        patch("server.app.tag_file", return_value=mock_path),
    ):
        mock_filepath_cls.return_value.exists.return_value = True
        response = await client.post(
            "/api/retag",
            json={"filepath": str(mock_path), "metadata": SAMPLE_ENRICHED_DICT},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["filepath"] == str(mock_path)


async def test_retag_file_not_found(client: AsyncClient) -> None:
    with patch("server.app.Path") as mock_filepath_cls:
        mock_filepath_cls.return_value.exists.return_value = False
        response = await client.post(
            "/api/retag",
            json={"filepath": "/nonexistent/file.m4a", "metadata": SAMPLE_ENRICHED_DICT},
        )
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "file_not_found"


async def test_retag_tagging_error(client: AsyncClient) -> None:
    from server.tagger import TaggingError

    mock_path = Path("/tmp/broken.xyz")
    with (
        patch("server.app.Path") as mock_filepath_cls,
        patch(
            "server.app.tag_file",
            side_effect=TaggingError("Unsupported format: .xyz", mock_path),
        ),
    ):
        mock_filepath_cls.return_value.exists.return_value = True
        response = await client.post(
            "/api/retag",
            json={"filepath": str(mock_path), "metadata": SAMPLE_ENRICHED_DICT},
        )
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "tagging_failed"


SAMPLE_ANALYSIS = AnalysisResult(
    bpm=128.0,
    key="Am",
    key_camelot="8A",
    beats=[0.234],
    downbeats=[0.234],
    segments=[
        SegmentInfo(
            label="Intro (32 bars)", original_label="intro", start=0.234, end=60.5, bars=32
        ),
    ],
    vdj_written=False,
)


async def test_analyze_success(client: AsyncClient) -> None:
    with (
        patch("server.app.Path") as mock_fp_cls,
        patch("server.app.analyze_audio", new_callable=AsyncMock, return_value=SAMPLE_ANALYSIS),
    ):
        mock_fp_cls.return_value.exists.return_value = True
        response = await client.post("/api/analyze", json={"filepath": "/path/to/track.m4a"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["analysis"]["bpm"] == 128.0
    assert data["analysis"]["key"] == "Am"


async def test_analyze_file_not_found(client: AsyncClient) -> None:
    with patch("server.app.Path") as mock_fp_cls:
        mock_fp_cls.return_value.exists.return_value = False
        response = await client.post("/api/analyze", json={"filepath": "/nonexistent.m4a"})
    assert response.status_code == 404
    assert response.json()["error"] == "file_not_found"


async def test_analyze_failure(client: AsyncClient) -> None:
    with (
        patch("server.app.Path") as mock_fp_cls,
        patch("server.app.analyze_audio", new_callable=AsyncMock, return_value=None),
    ):
        mock_fp_cls.return_value.exists.return_value = True
        response = await client.post("/api/analyze", json={"filepath": "/path/to/track.m4a"})
    assert response.status_code == 500
    assert response.json()["error"] == "analysis_failed"
