"""Tests for server/analyzer.py — HTTP client for analyzer container."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from server.analyzer import _to_container_path, analyze_audio


SAMPLE_ANALYSIS_JSON = {
    "status": "ok",
    "analysis": {
        "bpm": 128.0,
        "key": "Am",
        "key_camelot": "8A",
        "beats": [0.234, 0.703],
        "downbeats": [0.234],
        "segments": [
            {
                "label": "Intro",
                "original_label": "intro",
                "start": 0.234,
                "end": 60.5,
                "bars": 32,
            }
        ],
    },
}


def test_to_container_path_with_output_dir() -> None:
    filepath = Path("/Users/me/Music/DJ Library/Artist - Title.m4a")
    output_dir = Path("/Users/me/Music/DJ Library")
    assert _to_container_path(filepath, output_dir) == "/audio/Artist - Title.m4a"


def test_to_container_path_subdirectory() -> None:
    filepath = Path("/Users/me/Music/DJ Library/EDM/Artist - Title.m4a")
    output_dir = Path("/Users/me/Music/DJ Library")
    assert _to_container_path(filepath, output_dir) == "/audio/EDM/Artist - Title.m4a"


def test_to_container_path_fallback_no_output_dir() -> None:
    filepath = Path("/some/other/path/track.m4a")
    assert _to_container_path(filepath, None) == "/audio/track.m4a"


def test_to_container_path_fallback_not_relative() -> None:
    filepath = Path("/other/path/track.m4a")
    output_dir = Path("/Users/me/Music/DJ Library")
    assert _to_container_path(filepath, output_dir) == "/audio/track.m4a"


async def test_analyze_success() -> None:
    mock_response = httpx.Response(200, json=SAMPLE_ANALYSIS_JSON)
    with patch("server.analyzer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(
            Path("/Users/me/Music/DJ Library/track.m4a"),
            output_dir=Path("/Users/me/Music/DJ Library"),
        )

    assert result is not None
    assert result.bpm == 128.0
    assert result.key == "Am"
    assert len(result.segments) == 1


async def test_analyze_container_unreachable() -> None:
    with patch("server.analyzer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(Path("/path/to/track.m4a"))

    assert result is None


async def test_analyze_container_error_response() -> None:
    error_json = {"status": "error", "message": "Analysis failed"}
    mock_response = httpx.Response(200, json=error_json)
    with patch("server.analyzer.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(Path("/path/to/track.m4a"))

    assert result is None


async def test_analyze_writes_vdj_on_success(tmp_path: Path) -> None:
    mock_response = httpx.Response(200, json=SAMPLE_ANALYSIS_JSON)
    with (
        patch("server.analyzer.httpx.AsyncClient") as mock_client_cls,
        patch("server.vdj.write_to_vdj_database") as mock_vdj,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await analyze_audio(
            Path("/Users/me/Music/DJ Library/track.m4a"),
            vdj_db_path=tmp_path / "database.xml",
            output_dir=Path("/Users/me/Music/DJ Library"),
        )

    assert result is not None
    mock_vdj.assert_called_once()
