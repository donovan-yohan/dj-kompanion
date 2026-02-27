from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mutagen.flac import FLAC
from mutagen.id3 import COMM, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPUB, TXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggvorbis import OggVorbis

from server.models import EnrichedMetadata

if TYPE_CHECKING:
    from pathlib import Path

_ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|]')
_MULTI_SPACE = re.compile(r" +")
_MAX_FILENAME_LEN = 200


class TaggingError(Exception):
    """Raised when tagging fails."""

    def __init__(self, message: str, filepath: Path) -> None:
        super().__init__(message)
        self.message = message
        self.filepath = filepath


def sanitize_filename(name: str) -> str:
    """Strip illegal filesystem characters, collapse spaces, and truncate to 200 chars."""
    name = _ILLEGAL_CHARS.sub("", name)
    name = _MULTI_SPACE.sub(" ", name)
    name = name.strip()
    return name[:_MAX_FILENAME_LEN]


def build_download_filename(artist: str, title: str) -> str:
    """Return sanitized '{Artist} - {Title}' for use as a download filename (no extension).

    Falls back to 'download' if either part is empty after sanitization.
    """
    artist_clean = sanitize_filename(artist)
    title_clean = sanitize_filename(title)
    if artist_clean and title_clean:
        return f"{artist_clean} - {title_clean}"
    return "download"


def _build_tagged_filename(artist: str, title: str, ext: str) -> str | None:
    """Return sanitized '{Artist} - {Title}.{ext}', or None if either part is empty."""
    artist_clean = sanitize_filename(artist)
    title_clean = sanitize_filename(title)
    if not artist_clean or not title_clean:
        return None
    base = f"{artist_clean} - {title_clean}"
    return f"{base}.{ext}" if ext else base


def _safe_int(value: str | None) -> int | None:
    """Parse a string to int, returning None if not a valid integer."""
    if value and value.isdigit():
        return int(value)
    return None


# --- Writers ---


def _tag_mp3(filepath: Path, metadata: EnrichedMetadata) -> None:
    audio: Any = MP3(filepath)
    if audio.tags is None:
        audio.add_tags()
    tags: Any = audio.tags
    assert tags is not None

    tags.add(TPE1(encoding=3, text=metadata.artist))
    tags.add(TIT2(encoding=3, text=metadata.title))
    if metadata.genre is not None:
        tags.add(TCON(encoding=3, text=metadata.genre))
    if metadata.year is not None:
        tags.add(TDRC(encoding=3, text=str(metadata.year)))
    if metadata.label is not None:
        tags.add(TPUB(encoding=3, text=metadata.label))
    if metadata.energy is not None:
        tags.add(TXXX(encoding=3, desc="ENERGY", text=str(metadata.energy)))
    if metadata.bpm is not None:
        tags.add(TBPM(encoding=3, text=str(metadata.bpm)))
    if metadata.key is not None:
        tags.add(TKEY(encoding=3, text=metadata.key))
    if metadata.comment:
        tags.add(COMM(encoding=3, lang="eng", desc="", text=metadata.comment))
    audio.save()


def _tag_vorbis(filepath: Path, metadata: EnrichedMetadata, *, is_flac: bool) -> None:
    """Write Vorbis comment tags to FLAC or OGG files.

    FLAC stores values as plain strings; OGG Vorbis stores them as single-item lists.
    """
    audio: Any = FLAC(filepath) if is_flac else OggVorbis(filepath)

    def val(s: str) -> str | list[str]:
        return s if is_flac else [s]

    audio["ARTIST"] = val(metadata.artist)
    audio["TITLE"] = val(metadata.title)
    if metadata.genre is not None:
        audio["GENRE"] = val(metadata.genre)
    if metadata.year is not None:
        audio["DATE"] = val(str(metadata.year))
    if metadata.label is not None:
        audio["LABEL"] = val(metadata.label)
    if metadata.energy is not None:
        audio["ENERGY"] = val(str(metadata.energy))
    if metadata.bpm is not None:
        audio["BPM"] = val(str(metadata.bpm))
    if metadata.key is not None:
        audio["INITIALKEY"] = val(metadata.key)
    if metadata.comment:
        audio["COMMENT"] = val(metadata.comment)
    audio.save()


def _tag_m4a(filepath: Path, metadata: EnrichedMetadata) -> None:
    audio: Any = MP4(filepath)
    audio["\xa9ART"] = [metadata.artist]
    audio["\xa9nam"] = [metadata.title]
    if metadata.genre is not None:
        audio["\xa9gen"] = [metadata.genre]
    if metadata.year is not None:
        audio["\xa9day"] = [str(metadata.year)]
    if metadata.label is not None:
        audio["----:com.apple.iTunes:LABEL"] = [MP4FreeForm(metadata.label.encode())]
    if metadata.energy is not None:
        audio["----:com.apple.iTunes:ENERGY"] = [MP4FreeForm(str(metadata.energy).encode())]
    if metadata.bpm is not None:
        audio["tmpo"] = [metadata.bpm]
    if metadata.key is not None:
        audio["----:com.apple.iTunes:initialkey"] = [MP4FreeForm(metadata.key.encode())]
    if metadata.comment:
        audio["\xa9cmt"] = [metadata.comment]
    audio.save()


# --- Readers ---


def _first_vorbis_tag(audio: Any, key: str) -> str | None:
    """Return the first value for a Vorbis comment key, or None."""
    val: Any = audio.get(key)
    if not val:
        return None
    if isinstance(val, list) and val:
        return str(val[0])
    return str(val)


def _read_mp3(filepath: Path) -> EnrichedMetadata:
    audio: Any = MP3(filepath)
    tags: Any = audio.tags

    def get_text(key: str) -> str | None:
        if tags is None:
            return None
        frame: Any = tags.get(key)
        if frame is None:
            return None
        text = str(frame)
        return text if text else None

    def get_txxx(desc: str) -> str | None:
        if tags is None:
            return None
        frame: Any = tags.get(f"TXXX:{desc}")
        if frame is None:
            return None
        text = str(frame)
        return text if text else None

    artist = get_text("TPE1") or ""
    title_val = get_text("TIT2") or ""
    year_str = get_text("TDRC")
    bpm_str = get_text("TBPM")

    comment = ""
    if tags is not None:
        for tag_key in tags:
            if tag_key.startswith("COMM:"):
                frame: Any = tags.get(tag_key)
                if frame is not None:
                    comment = str(frame)
                break

    return EnrichedMetadata(
        artist=artist,
        title=title_val,
        genre=get_text("TCON"),
        year=_safe_int(year_str),
        label=get_text("TPUB"),
        energy=_safe_int(get_txxx("ENERGY")),
        bpm=_safe_int(bpm_str),
        key=get_text("TKEY"),
        comment=comment,
    )


def _read_vorbis(filepath: Path, *, is_flac: bool) -> EnrichedMetadata:
    """Read Vorbis comment tags from FLAC or OGG files."""
    audio: Any = FLAC(filepath) if is_flac else OggVorbis(filepath)

    return EnrichedMetadata(
        artist=_first_vorbis_tag(audio, "ARTIST") or "",
        title=_first_vorbis_tag(audio, "TITLE") or "",
        genre=_first_vorbis_tag(audio, "GENRE"),
        year=_safe_int(_first_vorbis_tag(audio, "DATE")),
        label=_first_vorbis_tag(audio, "LABEL"),
        energy=_safe_int(_first_vorbis_tag(audio, "ENERGY")),
        bpm=_safe_int(_first_vorbis_tag(audio, "BPM")),
        key=_first_vorbis_tag(audio, "INITIALKEY"),
        comment=_first_vorbis_tag(audio, "COMMENT") or "",
    )


def _read_m4a(filepath: Path) -> EnrichedMetadata:
    audio: Any = MP4(filepath)

    def get_str(key: str) -> str | None:
        val: Any = audio.get(key)
        if not val:
            return None
        item: Any = val[0]
        if isinstance(item, MP4FreeForm):
            return bytes(item).decode("utf-8", errors="replace")
        return str(item) if item is not None else None

    def get_freeform(key: str) -> str | None:
        val: Any = audio.get(key)
        if not val:
            return None
        return bytes(val[0]).decode("utf-8", errors="replace")

    bpm_raw: Any = audio.get("tmpo")
    bpm = int(bpm_raw[0]) if bpm_raw else None

    return EnrichedMetadata(
        artist=get_str("\xa9ART") or "",
        title=get_str("\xa9nam") or "",
        genre=get_str("\xa9gen"),
        year=_safe_int(get_str("\xa9day")),
        label=get_freeform("----:com.apple.iTunes:LABEL"),
        energy=_safe_int(get_freeform("----:com.apple.iTunes:ENERGY")),
        bpm=bpm,
        key=get_freeform("----:com.apple.iTunes:initialkey"),
        comment=get_str("\xa9cmt") or "",
    )


# --- Format dispatch tables ---

_TagWriter = Callable[["Path", EnrichedMetadata], None]
_TagReader = Callable[["Path"], EnrichedMetadata]

_WRITERS: dict[str, _TagWriter] = {
    "mp3": _tag_mp3,
    "flac": lambda fp, meta: _tag_vorbis(fp, meta, is_flac=True),
    "m4a": _tag_m4a,
    "mp4": _tag_m4a,
    "ogg": lambda fp, meta: _tag_vorbis(fp, meta, is_flac=False),
}

_READERS: dict[str, _TagReader] = {
    "mp3": _read_mp3,
    "flac": lambda fp: _read_vorbis(fp, is_flac=True),
    "m4a": _read_m4a,
    "mp4": _read_m4a,
    "ogg": lambda fp: _read_vorbis(fp, is_flac=False),
}


# --- Public API ---


def tag_file(filepath: Path, metadata: EnrichedMetadata) -> Path:
    """Embed metadata tags into an audio file.

    Returns the (possibly renamed) file path.
    Raises TaggingError if the format is unsupported or the file is corrupt.
    """
    ext = filepath.suffix.lower().lstrip(".")
    writer = _WRITERS.get(ext)

    if writer is None:
        raise TaggingError(f"Unsupported format: .{ext}", filepath)

    try:
        writer(filepath, metadata)
    except TaggingError:
        raise
    except Exception as exc:
        raise TaggingError(str(exc), filepath) from exc

    new_name = _build_tagged_filename(metadata.artist, metadata.title, ext)
    if new_name:
        new_path = filepath.parent / new_name
        if new_path != filepath:
            try:
                filepath.rename(new_path)
            except OSError as exc:
                raise TaggingError(f"Failed to rename file: {exc}", filepath) from exc
            return new_path

    return filepath


def read_tags(filepath: Path) -> EnrichedMetadata:
    """Read existing tags from an audio file.

    Returns an EnrichedMetadata with whatever fields are present.
    Raises TaggingError if the format is unsupported or the file is corrupt.
    """
    ext = filepath.suffix.lower().lstrip(".")
    reader = _READERS.get(ext)

    if reader is None:
        raise TaggingError(f"Unsupported format: .{ext}", filepath)

    try:
        return reader(filepath)
    except TaggingError:
        raise
    except Exception as exc:
        raise TaggingError(str(exc), filepath) from exc
