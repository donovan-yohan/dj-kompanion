from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.downloader import DownloadError, _download_audio_sync, download_audio, extract_metadata

# ── representative yt-dlp info dicts ──────────────────────────────────────────

YOUTUBE_INFO: dict[str, object] = {
    "title": "Test Song",
    "uploader": "Test Artist",
    "duration": 180,
    "upload_date": "20240101",
    "description": "A test song",
    "tags": ["music", "test"],
    "categories": ["Music"],
    "webpage_url": "https://www.youtube.com/watch?v=test123",
}

SOUNDCLOUD_INFO: dict[str, object] = {
    "title": "My Track",
    "uploader": "DJ Name",
    "duration": 240.5,
    "upload_date": "20231201",
    "description": None,
    "tags": [],
    "categories": [],
    "webpage_url": "https://soundcloud.com/artist/track",
}

# Bandcamp omits "uploader" and uses "artist" instead
BANDCAMP_INFO: dict[str, object] = {
    "title": "Album Track",
    "artist": "Bandcamp Artist",
    "duration": 300,
    "upload_date": "20230601",
    "description": "From my album",
    "tags": ["indie", "electronic"],
    "webpage_url": "https://artist.bandcamp.com/track/name",
}


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_ydl_mock(
    info: dict[str, object] | None,
    filename: str = "/tmp/test.webm",
) -> MagicMock:
    """Return a patched yt_dlp.YoutubeDL class whose context manager yields a
    mock instance with pre-configured extract_info / prepare_filename."""
    instance = MagicMock()
    instance.extract_info.return_value = info
    instance.prepare_filename.return_value = filename

    ydl_class = MagicMock()
    ydl_class.return_value.__enter__ = MagicMock(return_value=instance)
    ydl_class.return_value.__exit__ = MagicMock(return_value=False)
    return ydl_class


def _make_raising_ydl_mock(exc: Exception) -> MagicMock:
    instance = MagicMock()
    instance.extract_info.side_effect = exc

    ydl_class = MagicMock()
    ydl_class.return_value.__enter__ = MagicMock(return_value=instance)
    ydl_class.return_value.__exit__ = MagicMock(return_value=False)
    return ydl_class


# ── extract_metadata ──────────────────────────────────────────────────────────


class TestExtractMetadata:
    def test_youtube_metadata(self) -> None:
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(YOUTUBE_INFO)):
            result = asyncio.run(extract_metadata("https://youtube.com/watch?v=test"))

        assert result.title == "Test Song"
        assert result.uploader == "Test Artist"
        assert result.duration == 180
        assert result.upload_date == "20240101"
        assert result.description == "A test song"
        assert "music" in result.tags
        assert "test" in result.tags
        assert "Music" in result.tags
        assert result.source_url == "https://www.youtube.com/watch?v=test123"

    def test_soundcloud_metadata(self) -> None:
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(SOUNDCLOUD_INFO)):
            result = asyncio.run(extract_metadata("https://soundcloud.com/artist/track"))

        assert result.title == "My Track"
        assert result.uploader == "DJ Name"
        assert result.duration == 240  # float truncated to int
        assert result.tags == []

    def test_bandcamp_uses_artist_field(self) -> None:
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(BANDCAMP_INFO)):
            result = asyncio.run(extract_metadata("https://artist.bandcamp.com/track/name"))

        assert result.uploader == "Bandcamp Artist"

    def test_tags_deduplicated_across_tags_and_categories(self) -> None:
        info: dict[str, object] = {
            **YOUTUBE_INFO,
            "tags": ["electronic", "music"],
            "categories": ["Music", "Dance"],  # "Music" duplicated from tags
        }
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(info)):
            result = asyncio.run(extract_metadata("https://youtube.com/watch?v=test"))

        assert result.tags.count("Music") == 1

    def test_missing_uploader_returns_none(self) -> None:
        info: dict[str, object] = {
            "title": "No Uploader",
            "duration": 60,
            "tags": [],
            "webpage_url": "https://example.com/track",
        }
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(info)):
            result = asyncio.run(extract_metadata("https://example.com/track"))

        assert result.uploader is None

    def test_none_info_raises_download_error(self) -> None:
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(None)):
            with pytest.raises(DownloadError):
                asyncio.run(extract_metadata("https://example.com"))

    def test_yt_dlp_exception_raises_download_error(self) -> None:
        mock = _make_raising_ydl_mock(Exception("Unsupported URL"))
        with patch("server.downloader.yt_dlp.YoutubeDL", mock):
            with pytest.raises(DownloadError) as exc_info:
                asyncio.run(extract_metadata("https://example.com"))

        assert exc_info.value.url == "https://example.com"
        assert "Unsupported URL" in exc_info.value.message

    def test_source_url_falls_back_to_input_url(self) -> None:
        info: dict[str, object] = {"title": "Track", "tags": []}
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(info)):
            result = asyncio.run(extract_metadata("https://fallback.example.com"))

        assert result.source_url == "https://fallback.example.com"


# ── download_audio ────────────────────────────────────────────────────────────


class TestDownloadAudio:
    def test_returns_path(self, tmp_path: Path) -> None:
        expected = str(tmp_path / "test.webm")
        mock = _make_ydl_mock(YOUTUBE_INFO, filename=expected)

        with patch("server.downloader.yt_dlp.YoutubeDL", mock):
            result = asyncio.run(
                download_audio(
                    url="https://youtube.com/watch?v=test",
                    output_dir=tmp_path,
                    filename="test",
                )
            )

        assert result == Path(expected)

    def test_best_format_preserves_extension(self, tmp_path: Path) -> None:
        base = str(tmp_path / "test.opus")
        mock = _make_ydl_mock(YOUTUBE_INFO, filename=base)

        with patch("server.downloader.yt_dlp.YoutubeDL", mock):
            result = asyncio.run(
                download_audio(
                    url="https://youtube.com/watch?v=test",
                    output_dir=tmp_path,
                    filename="test",
                    preferred_format="best",
                )
            )

        assert result.suffix == ".opus"

    @pytest.mark.parametrize("fmt", ["mp3", "flac", "m4a"])
    def test_format_conversion(self, tmp_path: Path, fmt: str) -> None:
        base = str(tmp_path / "test.webm")
        mock = _make_ydl_mock(YOUTUBE_INFO, filename=base)

        with patch("server.downloader.yt_dlp.YoutubeDL", mock):
            result = asyncio.run(
                download_audio(
                    url="https://youtube.com/watch?v=test",
                    output_dir=tmp_path,
                    filename="test",
                    preferred_format=fmt,
                )
            )

        assert result.suffix == f".{fmt}"

    def test_postprocessors_set_for_format(self, tmp_path: Path) -> None:
        mock = _make_ydl_mock(YOUTUBE_INFO, str(tmp_path / "test.webm"))

        with patch("server.downloader.yt_dlp.YoutubeDL", mock) as patched:
            asyncio.run(
                download_audio(
                    url="https://youtube.com/watch?v=test",
                    output_dir=tmp_path,
                    filename="test",
                    preferred_format="mp3",
                )
            )

        opts = patched.call_args[0][0]
        assert any(p["key"] == "FFmpegExtractAudio" for p in opts["postprocessors"])
        assert opts["postprocessors"][0]["preferredcodec"] == "mp3"

    def test_no_postprocessors_for_best(self, tmp_path: Path) -> None:
        mock = _make_ydl_mock(YOUTUBE_INFO, str(tmp_path / "test.webm"))

        with patch("server.downloader.yt_dlp.YoutubeDL", mock) as patched:
            asyncio.run(
                download_audio(
                    url="https://youtube.com/watch?v=test",
                    output_dir=tmp_path,
                    filename="test",
                    preferred_format="best",
                )
            )

        opts = patched.call_args[0][0]
        assert opts["postprocessors"] == []

    def test_none_info_raises_download_error(self, tmp_path: Path) -> None:
        with patch("server.downloader.yt_dlp.YoutubeDL", _make_ydl_mock(None)):
            with pytest.raises(DownloadError):
                asyncio.run(
                    download_audio(
                        url="https://youtube.com/watch?v=test",
                        output_dir=tmp_path,
                        filename="test",
                    )
                )

    def test_yt_dlp_exception_raises_download_error(self, tmp_path: Path) -> None:
        mock = _make_raising_ydl_mock(Exception("Network error"))
        with patch("server.downloader.yt_dlp.YoutubeDL", mock):
            with pytest.raises(DownloadError) as exc_info:
                asyncio.run(
                    download_audio(
                        url="https://youtube.com/watch?v=test",
                        output_dir=tmp_path,
                        filename="test",
                    )
                )

        assert "Network error" in exc_info.value.message

    def test_download_best_format_has_extension(self, tmp_path: Path) -> None:
        """When preferred_format is 'best', returned path must have file extension."""
        info: dict[str, Any] = {"id": "test123", "title": "Test", "ext": "webm"}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.prepare_filename.return_value = str(tmp_path / "Artist - Title.webm")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("server.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = _download_audio_sync(
                url="https://example.com",
                output_dir=tmp_path,
                filename="Artist - Title",
                preferred_format="best",
            )

        assert result.suffix != "", f"Expected file extension, got: {result}"
        assert result.suffix == ".webm"

    def test_download_preferred_format_overrides_extension(self, tmp_path: Path) -> None:
        """When preferred_format is set, extension should match it."""
        info: dict[str, Any] = {"id": "test123", "title": "Test", "ext": "webm"}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.prepare_filename.return_value = str(tmp_path / "Artist - Title.webm")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("server.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = _download_audio_sync(
                url="https://example.com",
                output_dir=tmp_path,
                filename="Artist - Title",
                preferred_format="mp3",
            )

        assert result.suffix == ".mp3"

    def test_download_outtmpl_includes_ext_placeholder(self, tmp_path: Path) -> None:
        """Verify outtmpl includes %(ext)s so yt-dlp adds the extension."""
        info: dict[str, Any] = {"id": "test123", "title": "Test", "ext": "m4a"}
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.prepare_filename.return_value = str(tmp_path / "Artist - Title.m4a")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        captured_opts: list[dict[str, Any]] = []

        def capture_init(*args: Any, **kwargs: Any) -> MagicMock:
            if args:
                captured_opts.append(args[0])
            return mock_ydl

        with patch("server.downloader.yt_dlp.YoutubeDL", side_effect=capture_init):
            _download_audio_sync(
                url="https://example.com",
                output_dir=tmp_path,
                filename="Artist - Title",
                preferred_format="best",
            )

        assert captured_opts, "YoutubeDL was not called"
        outtmpl = captured_opts[0]["outtmpl"]
        assert "%(ext)s" in outtmpl, f"outtmpl missing %(ext)s: {outtmpl}"
