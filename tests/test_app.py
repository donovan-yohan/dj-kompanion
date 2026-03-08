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


async def test_download_success(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
        patch("server.app.upsert_track"),
        patch("server.app.asyncio.create_task"),
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
        patch("server.app.search_metadata", new_callable=AsyncMock, return_value=[]),
        patch(
            "server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
        patch("server.app.upsert_track"),
        patch("server.app.asyncio.create_task"),
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


async def test_download_with_api_and_claude_enrichment(client: AsyncClient) -> None:
    from server.metadata_lookup import MetadataCandidate

    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    mock_candidates = [
        MetadataCandidate(source="musicbrainz", artist="DJ Snake", title="Turn Down for What")
    ]
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.search_metadata", new_callable=AsyncMock, return_value=mock_candidates),
        patch(
            "server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
        patch("server.app.upsert_track"),
        patch("server.app.asyncio.create_task"),
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
    assert data["enrichment_source"] == "api+claude"


async def test_download_claude_fails_gracefully(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=True),
        patch("server.app.search_metadata", new_callable=AsyncMock, return_value=[]),
        patch("server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=None),
        patch("server.app.upsert_track"),
        patch("server.app.asyncio.create_task"),
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
        patch("server.app.search_metadata", new_callable=AsyncMock, return_value=[]),
        patch(
            "server.app.try_enrich_metadata", new_callable=AsyncMock, return_value=claude_enriched
        ),
        patch("server.app.upsert_track"),
        patch("server.app.asyncio.create_task"),
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


async def test_download_without_raw_extracts_metadata(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW),
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
        patch("server.app.upsert_track"),
        patch("server.app.asyncio.create_task"),
    ):
        response = await client.post(
            "/api/download",
            json={
                "url": "https://www.youtube.com/watch?v=HMUDVMiITOU",
                "metadata": {"artist": "DJ Snake", "title": "Turn Down for What"},
                "format": "best",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"


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


async def test_resolve_playlist_success(client: AsyncClient) -> None:
    mock_tracks = [
        ("https://www.youtube.com/watch?v=abc", "Track 1"),
        ("https://www.youtube.com/watch?v=def", "Track 2"),
    ]
    with patch(
        "server.app.resolve_playlist",
        new_callable=AsyncMock,
        return_value=("My Playlist", mock_tracks),
    ):
        response = await client.post(
            "/api/resolve-playlist",
            json={"url": "https://www.youtube.com/playlist?list=PLxyz"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["playlist_title"] == "My Playlist"
    assert len(data["tracks"]) == 2
    assert data["tracks"][0]["url"] == "https://www.youtube.com/watch?v=abc"
    assert data["tracks"][0]["title"] == "Track 1"


async def test_resolve_playlist_failure(client: AsyncClient) -> None:
    with patch(
        "server.app.resolve_playlist",
        new_callable=AsyncMock,
        side_effect=DownloadError("Not a playlist", url="https://example.com"),
    ):
        response = await client.post(
            "/api/resolve-playlist",
            json={"url": "https://example.com"},
        )
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "playlist_resolve_failed"


async def test_sync_vdj_endpoint(client: AsyncClient) -> None:
    from server.vdj_sync import SyncResult

    mock_result = SyncResult(synced=2, skipped=1, errors=[], refused=False)
    with patch("server.app.sync_vdj", return_value=mock_result):
        response = await client.post("/api/sync-vdj")
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 2
    assert data["skipped"] == 1
    assert data["refused"] is False
    assert data["status"] == "ok"


async def test_sync_vdj_refused(client: AsyncClient) -> None:
    from server.vdj_sync import SyncResult

    mock_result = SyncResult(synced=0, skipped=0, errors=[], refused=True)
    with patch("server.app.sync_vdj", return_value=mock_result):
        response = await client.post("/api/sync-vdj")
    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is True
    assert data["status"] == "refused"


async def test_tracks_endpoint(client: AsyncClient) -> None:
    from server.track_db import TrackRow

    mock_tracks = [
        TrackRow(
            id=1,
            filepath="/music/track.m4a",
            analysis_path="/analysis/track.json",
            status="analyzed",
            error=None,
            analyzed_at="2026-01-01T00:00:00",
            synced_at=None,
            created_at="2026-01-01T00:00:00",
        ),
    ]
    with patch("server.app.get_all_tracks", return_value=mock_tracks):
        response = await client.get("/api/tracks")
    assert response.status_code == 200
    data = response.json()
    assert "tracks" in data
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["filepath"] == "/music/track.m4a"
    assert data["tracks"][0]["status"] == "analyzed"


async def test_tracks_endpoint_empty(client: AsyncClient) -> None:
    with patch("server.app.get_all_tracks", return_value=[]):
        response = await client.get("/api/tracks")
    assert response.status_code == 200
    data = response.json()
    assert data["tracks"] == []


async def test_reanalyze_not_found(client: AsyncClient) -> None:
    with patch("server.app.get_track", return_value=None):
        response = await client.post("/api/reanalyze", json={"filepath": "/nonexistent.m4a"})
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_reanalyze_success(client: AsyncClient) -> None:
    from server.track_db import TrackRow

    mock_track = TrackRow(
        id=1,
        filepath="/music/track.m4a",
        analysis_path=None,
        status="failed",
        error="previous error",
        analyzed_at=None,
        synced_at=None,
        created_at="2026-01-01T00:00:00",
    )
    with (
        patch("server.app.get_track", return_value=mock_track),
        patch("server.app.upsert_track"),
        patch("server.app.analyze_audio", new_callable=AsyncMock),
    ):
        response = await client.post("/api/reanalyze", json={"filepath": "/music/track.m4a"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"


async def test_download_inserts_track_and_fires_analysis(client: AsyncClient) -> None:
    mock_path = Path("/tmp/DJ Snake - Turn Down for What.m4a")
    with (
        patch("server.app.download_audio", new_callable=AsyncMock, return_value=mock_path),
        patch("server.app.tag_file", return_value=mock_path),
        patch("server.app.is_claude_available", new_callable=AsyncMock, return_value=False),
        patch("server.app.upsert_track") as mock_upsert,
        patch("server.app.analyze_audio", new_callable=AsyncMock) as mock_analyze,
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
    mock_upsert.assert_called_once()
    # analyze_audio is called to create the coroutine passed to asyncio.create_task
    mock_analyze.assert_called_once()
