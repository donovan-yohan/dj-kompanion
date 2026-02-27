from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yt_dlp  # type: ignore[import-untyped]

from server.models import RawMetadata


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


def _extract_metadata_sync(url: str) -> RawMetadata:
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
    }
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


async def extract_metadata(url: str) -> RawMetadata:
    """Extract metadata from URL without downloading.

    Used for the preview step.
    Raises DownloadError on failure.
    """
    return await asyncio.to_thread(_extract_metadata_sync, url)


def _download_audio_sync(
    url: str,
    output_dir: Path,
    filename: str,
    preferred_format: str,
) -> Path:
    postprocessors: list[dict[str, Any]] = []

    if preferred_format != "best":
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": preferred_format,
                "preferredquality": "0",
            }
        )

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / filename) + ".%(ext)s",
        "postprocessors": postprocessors,
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info: dict[str, Any] | None = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError("Download returned no info", url=url)
            filepath: str = ydl.prepare_filename(info)
            path = Path(filepath)
            if preferred_format != "best":
                path = path.with_suffix(f".{preferred_format}")
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
) -> Path:
    """Download best available audio, optionally convert format.

    Returns the path to the downloaded file.
    Raises DownloadError on failure.
    """
    return await asyncio.to_thread(
        _download_audio_sync, url, output_dir, filename, preferred_format
    )
