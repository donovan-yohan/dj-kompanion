from __future__ import annotations

import asyncio
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yt_dlp  # type: ignore[import-untyped]

from server.models import CookieItem, RawMetadata

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _cookie_file(cookies: list[CookieItem]) -> Iterator[str | None]:
    """Write cookies to a temporary Netscape-format cookie file for yt-dlp."""
    if not cookies:
        yield None
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=True) as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in cookies:
            host_only = not c.domain.startswith(".")
            expiry = int(c.expiration_date) if c.expiration_date else 0
            f.write(
                f"{c.domain}\t{'FALSE' if host_only else 'TRUE'}\t{c.path}"
                f"\t{'TRUE' if c.secure else 'FALSE'}\t{expiry}\t{c.name}\t{c.value}\n"
            )
        f.flush()
        yield f.name


class DownloadError(Exception):
    """Raised when yt-dlp extraction or download fails."""

    def __init__(self, message: str, url: str) -> None:
        super().__init__(message)
        self.message = message
        self.url = url


def _parse_info(info: dict[str, Any], url: str) -> RawMetadata:
    uploader: str | None = info.get("uploader") or info.get("artist") or info.get("creator") or None

    tags_list: list[str] = [str(t) for t in (info.get("tags") or [])]
    cats_list: list[str] = [str(t) for t in (info.get("categories") or [])]
    tags = list(dict.fromkeys(tags_list + cats_list))

    duration_raw = info.get("duration")
    duration: int | None = int(duration_raw) if duration_raw is not None else None

    source_url: str = info.get("webpage_url") or info.get("original_url") or url

    return RawMetadata(
        title=str(info.get("title") or ""),
        uploader=uploader,
        duration=duration,
        upload_date=info.get("upload_date"),
        description=info.get("description"),
        tags=tags,
        source_url=source_url,
    )


def _extract_metadata_sync(url: str, cookies: list[CookieItem] | None = None) -> RawMetadata:
    with _cookie_file(cookies or []) as cookie_path:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
        }
        if cookie_path:
            ydl_opts["cookiefile"] = cookie_path
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info: dict[str, Any] | None = ydl.extract_info(url, download=False)
                if info is None:
                    raise DownloadError("No metadata returned", url=url)
                return _parse_info(info, url)
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(str(exc), url=url) from exc


async def extract_metadata(url: str, cookies: list[CookieItem] | None = None) -> RawMetadata:
    """Extract metadata from URL without downloading.

    Used for the preview step.
    Raises DownloadError on failure.
    """
    return await asyncio.to_thread(_extract_metadata_sync, url, cookies)


_DEFAULT_AUDIO_FORMAT = "m4a"


def _download_audio_sync(
    url: str,
    output_dir: Path,
    filename: str,
    preferred_format: str,
    cookies: list[CookieItem] | None = None,
) -> Path:
    audio_format = _DEFAULT_AUDIO_FORMAT if preferred_format == "best" else preferred_format

    with _cookie_file(cookies or []) as cookie_path:
        ydl_opts: dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": str(output_dir / filename) + ".%(ext)s",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            ],
            "quiet": True,
        }
        if cookie_path:
            ydl_opts["cookiefile"] = cookie_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info: dict[str, Any] | None = ydl.extract_info(url, download=True)
                if info is None:
                    raise DownloadError("Download returned no info", url=url)
                filepath: str = ydl.prepare_filename(info)
                path = Path(filepath).with_suffix(f".{audio_format}")
                return path
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(str(exc), url=url) from exc


async def download_audio(
    url: str,
    output_dir: Path,
    filename: str,
    preferred_format: str = "best",
    cookies: list[CookieItem] | None = None,
) -> Path:
    """Download best available audio, optionally convert format.

    Returns the path to the downloaded file.
    Raises DownloadError on failure.
    """
    return await asyncio.to_thread(
        _download_audio_sync, url, output_dir, filename, preferred_format, cookies
    )
