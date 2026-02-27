from __future__ import annotations

import re
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


def _build_filename(artist: str, title: str, ext: str) -> str | None:
    """Return sanitized '{Artist} - {Title}.{ext}', or None if either part is empty."""
    artist_clean = sanitize_filename(artist)
    title_clean = sanitize_filename(title)
    if not artist_clean or not title_clean:
        return None
    base = f"{artist_clean} - {title_clean}"
    return f"{base}.{ext}" if ext else base


# ─── Writers ──────────────────────────────────────────────────────────────────


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


def _tag_flac(filepath: Path, metadata: EnrichedMetadata) -> None:
    audio: Any = FLAC(filepath)
    audio["ARTIST"] = metadata.artist
    audio["TITLE"] = metadata.title
    if metadata.genre is not None:
        audio["GENRE"] = metadata.genre
    if metadata.year is not None:
        audio["DATE"] = str(metadata.year)
    if metadata.label is not None:
        audio["LABEL"] = metadata.label
    if metadata.energy is not None:
        audio["ENERGY"] = str(metadata.energy)
    if metadata.bpm is not None:
        audio["BPM"] = str(metadata.bpm)
    if metadata.key is not None:
        audio["INITIALKEY"] = metadata.key
    if metadata.comment:
        audio["COMMENT"] = metadata.comment
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


def _tag_ogg(filepath: Path, metadata: EnrichedMetadata) -> None:
    audio: Any = OggVorbis(filepath)
    audio["ARTIST"] = [metadata.artist]
    audio["TITLE"] = [metadata.title]
    if metadata.genre is not None:
        audio["GENRE"] = [metadata.genre]
    if metadata.year is not None:
        audio["DATE"] = [str(metadata.year)]
    if metadata.label is not None:
        audio["LABEL"] = [metadata.label]
    if metadata.energy is not None:
        audio["ENERGY"] = [str(metadata.energy)]
    if metadata.bpm is not None:
        audio["BPM"] = [str(metadata.bpm)]
    if metadata.key is not None:
        audio["INITIALKEY"] = [metadata.key]
    if metadata.comment:
        audio["COMMENT"] = [metadata.comment]
    audio.save()


# ─── Readers ──────────────────────────────────────────────────────────────────


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
    genre = get_text("TCON")
    year_str = get_text("TDRC")
    label = get_text("TPUB")
    energy_str = get_txxx("ENERGY")
    bpm_str = get_text("TBPM")
    key = get_text("TKEY")

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
        genre=genre,
        year=int(year_str) if year_str and year_str.isdigit() else None,
        label=label,
        energy=int(energy_str) if energy_str and energy_str.isdigit() else None,
        bpm=int(bpm_str) if bpm_str and bpm_str.isdigit() else None,
        key=key,
        comment=comment,
    )


def _read_flac(filepath: Path) -> EnrichedMetadata:
    audio: Any = FLAC(filepath)
    artist = _first_vorbis_tag(audio, "ARTIST") or ""
    title_val = _first_vorbis_tag(audio, "TITLE") or ""
    genre = _first_vorbis_tag(audio, "GENRE")
    year_str = _first_vorbis_tag(audio, "DATE")
    label = _first_vorbis_tag(audio, "LABEL")
    energy_str = _first_vorbis_tag(audio, "ENERGY")
    bpm_str = _first_vorbis_tag(audio, "BPM")
    key = _first_vorbis_tag(audio, "INITIALKEY")
    comment = _first_vorbis_tag(audio, "COMMENT") or ""

    return EnrichedMetadata(
        artist=artist,
        title=title_val,
        genre=genre,
        year=int(year_str) if year_str and year_str.isdigit() else None,
        label=label,
        energy=int(energy_str) if energy_str and energy_str.isdigit() else None,
        bpm=int(bpm_str) if bpm_str and bpm_str.isdigit() else None,
        key=key,
        comment=comment,
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

    artist = get_str("\xa9ART") or ""
    title_val = get_str("\xa9nam") or ""
    genre = get_str("\xa9gen")
    year_str = get_str("\xa9day")
    label = get_freeform("----:com.apple.iTunes:LABEL")
    energy_str = get_freeform("----:com.apple.iTunes:ENERGY")
    bpm_raw: Any = audio.get("tmpo")
    bpm = int(bpm_raw[0]) if bpm_raw else None
    key = get_freeform("----:com.apple.iTunes:initialkey")
    comment = get_str("\xa9cmt") or ""

    return EnrichedMetadata(
        artist=artist,
        title=title_val,
        genre=genre,
        year=int(year_str) if year_str and year_str.isdigit() else None,
        label=label,
        energy=int(energy_str) if energy_str and energy_str.isdigit() else None,
        bpm=bpm,
        key=key,
        comment=comment,
    )


def _read_ogg(filepath: Path) -> EnrichedMetadata:
    audio: Any = OggVorbis(filepath)
    artist = _first_vorbis_tag(audio, "ARTIST") or ""
    title_val = _first_vorbis_tag(audio, "TITLE") or ""
    genre = _first_vorbis_tag(audio, "GENRE")
    year_str = _first_vorbis_tag(audio, "DATE")
    label = _first_vorbis_tag(audio, "LABEL")
    energy_str = _first_vorbis_tag(audio, "ENERGY")
    bpm_str = _first_vorbis_tag(audio, "BPM")
    key = _first_vorbis_tag(audio, "INITIALKEY")
    comment = _first_vorbis_tag(audio, "COMMENT") or ""

    return EnrichedMetadata(
        artist=artist,
        title=title_val,
        genre=genre,
        year=int(year_str) if year_str and year_str.isdigit() else None,
        label=label,
        energy=int(energy_str) if energy_str and energy_str.isdigit() else None,
        bpm=int(bpm_str) if bpm_str and bpm_str.isdigit() else None,
        key=key,
        comment=comment,
    )


# ─── Public API ───────────────────────────────────────────────────────────────


def tag_file(filepath: Path, metadata: EnrichedMetadata) -> Path:
    """Embed metadata tags into an audio file.

    Returns the (possibly renamed) file path.
    Raises TaggingError if the format is unsupported or the file is corrupt.
    """
    ext = filepath.suffix.lower().lstrip(".")

    try:
        if ext == "mp3":
            _tag_mp3(filepath, metadata)
        elif ext == "flac":
            _tag_flac(filepath, metadata)
        elif ext in ("m4a", "mp4"):
            _tag_m4a(filepath, metadata)
        elif ext == "ogg":
            _tag_ogg(filepath, metadata)
        else:
            raise TaggingError(f"Unsupported format: .{ext}", filepath)
    except TaggingError:
        raise
    except Exception as exc:
        raise TaggingError(str(exc), filepath) from exc

    new_name = _build_filename(metadata.artist, metadata.title, ext)
    if new_name:
        new_path = filepath.parent / new_name
        if new_path != filepath:
            filepath.rename(new_path)
            return new_path

    return filepath


def read_tags(filepath: Path) -> EnrichedMetadata:
    """Read existing tags from an audio file.

    Returns an EnrichedMetadata with whatever fields are present.
    Raises TaggingError if the format is unsupported or the file is corrupt.
    """
    ext = filepath.suffix.lower().lstrip(".")

    try:
        if ext == "mp3":
            return _read_mp3(filepath)
        elif ext == "flac":
            return _read_flac(filepath)
        elif ext in ("m4a", "mp4"):
            return _read_m4a(filepath)
        elif ext == "ogg":
            return _read_ogg(filepath)
        else:
            raise TaggingError(f"Unsupported format: .{ext}", filepath)
    except TaggingError:
        raise
    except Exception as exc:
        raise TaggingError(str(exc), filepath) from exc
