"""Tests for server/tagger.py — mutagen-based audio file tagging."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from server.models import EnrichedMetadata
from server.tagger import TaggingError, read_tags, sanitize_filename, tag_file

if TYPE_CHECKING:
    from pathlib import Path

HAS_FFMPEG = shutil.which("ffmpeg") is not None

FULL_META = EnrichedMetadata(
    artist="Test Artist",
    title="Test Title",
    genre="Electronic",
    year=2024,
    label="Test Label",
    energy=7,
    bpm=128,
    key="Am",
    comment="https://example.com/video",
)

MINIMAL_META = EnrichedMetadata(
    artist="Minimal Artist",
    title="Minimal Title",
)


def make_silent(path: Path) -> None:
    """Create a short silent audio file via ffmpeg; skip the test if unavailable."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not available")

    ext = path.suffix.lower().lstrip(".")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        "0.5",
    ]
    if ext == "m4a":
        cmd.extend(["-c:a", "aac"])
    cmd.append(str(path))

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg couldn't create .{ext}: {exc.stderr.decode()[:200]}")


# ─── sanitize_filename (no audio files needed) ────────────────────────────────


class TestSanitizeFilename:
    def test_strips_illegal_chars(self) -> None:
        assert sanitize_filename('AC/DC: "Back in Black"') == "ACDC Back in Black"

    def test_strips_all_illegal_chars(self) -> None:
        assert sanitize_filename('/\\:*?"<>|') == ""

    def test_collapses_multiple_spaces(self) -> None:
        assert sanitize_filename("Too   Many   Spaces") == "Too Many Spaces"

    def test_trims_leading_trailing_whitespace(self) -> None:
        assert sanitize_filename("  Leading and Trailing  ") == "Leading and Trailing"

    def test_truncates_to_200_chars(self) -> None:
        long_name = "A" * 300
        assert len(sanitize_filename(long_name)) == 200

    def test_empty_string_stays_empty(self) -> None:
        assert sanitize_filename("") == ""

    def test_normal_name_unchanged(self) -> None:
        assert sanitize_filename("Normal Name") == "Normal Name"

    def test_slash_in_artist_name(self) -> None:
        assert sanitize_filename("AC/DC") == "ACDC"

    def test_colon_in_title(self) -> None:
        assert sanitize_filename("Back in Black: Live") == "Back in Black Live"

    def test_spaces_after_illegal_char_removal_collapsed(self) -> None:
        # "A / B" → slash removed → "A  B" → collapsed → "A B"
        result = sanitize_filename("A / B")
        assert result == "A B"

    def test_question_mark_stripped(self) -> None:
        assert "?" not in sanitize_filename("What is this?")


# ─── Unsupported format ────────────────────────────────────────────────────────


class TestUnsupportedFormat:
    def test_raises_tagging_error_for_wav(self, tmp_path: Path) -> None:
        wav = tmp_path / "audio.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 40)
        with pytest.raises(TaggingError):
            tag_file(wav, FULL_META)

    def test_raises_tagging_error_for_unknown_ext(self, tmp_path: Path) -> None:
        f = tmp_path / "audio.xyz"
        f.write_bytes(b"dummy")
        with pytest.raises(TaggingError):
            tag_file(f, FULL_META)

    def test_tagging_error_carries_filepath(self, tmp_path: Path) -> None:
        f = tmp_path / "audio.xyz"
        f.write_bytes(b"dummy")
        with pytest.raises(TaggingError) as exc_info:
            tag_file(f, FULL_META)
        assert exc_info.value.filepath == f


# ─── MP3 ──────────────────────────────────────────────────────────────────────


class TestMp3Tagging:
    def test_full_round_trip(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent(fp)

        result = tag_file(fp, FULL_META)
        tags = read_tags(result)

        assert tags.artist == FULL_META.artist
        assert tags.title == FULL_META.title
        assert tags.genre == FULL_META.genre
        assert tags.year == FULL_META.year
        assert tags.bpm == FULL_META.bpm
        assert tags.key == FULL_META.key
        assert tags.comment == FULL_META.comment

    def test_file_renamed(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.mp3"
        make_silent(fp)

        result = tag_file(fp, FULL_META)

        assert result.name == "Test Artist - Test Title.mp3"
        assert not fp.exists()

    def test_none_fields_not_written(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent(fp)

        result = tag_file(fp, MINIMAL_META)
        tags = read_tags(result)

        assert tags.genre is None
        assert tags.year is None
        assert tags.label is None
        assert tags.energy is None
        assert tags.bpm is None
        assert tags.key is None

    def test_no_rename_when_already_correct(self, tmp_path: Path) -> None:
        fp = tmp_path / "Test Artist - Test Title.mp3"
        make_silent(fp)

        result = tag_file(fp, FULL_META)

        assert result == fp
        assert fp.exists()


# ─── FLAC ─────────────────────────────────────────────────────────────────────


class TestFlacTagging:
    def test_full_round_trip(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.flac"
        make_silent(fp)

        result = tag_file(fp, FULL_META)
        tags = read_tags(result)

        assert tags.artist == FULL_META.artist
        assert tags.title == FULL_META.title
        assert tags.genre == FULL_META.genre
        assert tags.year == FULL_META.year
        assert tags.label == FULL_META.label
        assert tags.energy == FULL_META.energy
        assert tags.bpm == FULL_META.bpm
        assert tags.key == FULL_META.key
        assert tags.comment == FULL_META.comment

    def test_file_renamed(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.flac"
        make_silent(fp)

        result = tag_file(fp, FULL_META)

        assert result.name == "Test Artist - Test Title.flac"
        assert not fp.exists()

    def test_none_fields_not_written(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.flac"
        make_silent(fp)

        result = tag_file(fp, MINIMAL_META)
        tags = read_tags(result)

        assert tags.genre is None
        assert tags.year is None
        assert tags.bpm is None


# ─── OGG ──────────────────────────────────────────────────────────────────────


class TestOggTagging:
    def test_full_round_trip(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.ogg"
        make_silent(fp)

        result = tag_file(fp, FULL_META)
        tags = read_tags(result)

        assert tags.artist == FULL_META.artist
        assert tags.title == FULL_META.title
        assert tags.genre == FULL_META.genre
        assert tags.year == FULL_META.year
        assert tags.label == FULL_META.label
        assert tags.energy == FULL_META.energy
        assert tags.bpm == FULL_META.bpm
        assert tags.key == FULL_META.key
        assert tags.comment == FULL_META.comment

    def test_file_renamed(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.ogg"
        make_silent(fp)

        result = tag_file(fp, FULL_META)

        assert result.name == "Test Artist - Test Title.ogg"

    def test_none_fields_not_written(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.ogg"
        make_silent(fp)

        result = tag_file(fp, MINIMAL_META)
        tags = read_tags(result)

        assert tags.genre is None
        assert tags.year is None


# ─── M4A ──────────────────────────────────────────────────────────────────────


class TestM4aTagging:
    def test_full_round_trip(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.m4a"
        make_silent(fp)

        result = tag_file(fp, FULL_META)
        tags = read_tags(result)

        assert tags.artist == FULL_META.artist
        assert tags.title == FULL_META.title
        assert tags.genre == FULL_META.genre
        assert tags.label == FULL_META.label
        assert tags.energy == FULL_META.energy
        assert tags.bpm == FULL_META.bpm
        assert tags.key == FULL_META.key
        assert tags.comment == FULL_META.comment

    def test_file_renamed(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.m4a"
        make_silent(fp)

        result = tag_file(fp, FULL_META)

        assert result.name == "Test Artist - Test Title.m4a"

    def test_none_fields_not_written(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.m4a"
        make_silent(fp)

        result = tag_file(fp, MINIMAL_META)
        tags = read_tags(result)

        assert tags.genre is None
        assert tags.bpm is None


# ─── Filename edge cases ──────────────────────────────────────────────────────


class TestFilenameEdgeCases:
    def test_illegal_chars_in_artist_sanitized(self, tmp_path: Path) -> None:
        fp = tmp_path / "test.mp3"
        make_silent(fp)

        meta = EnrichedMetadata(artist="AC/DC", title="Back in Black")
        result = tag_file(fp, meta)

        assert result.name == "ACDC - Back in Black.mp3"

    def test_empty_artist_keeps_original_name(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.mp3"
        make_silent(fp)

        meta = EnrichedMetadata(artist="", title="Some Title")
        result = tag_file(fp, meta)

        assert result.name == "original.mp3"

    def test_empty_title_keeps_original_name(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.mp3"
        make_silent(fp)

        meta = EnrichedMetadata(artist="Some Artist", title="")
        result = tag_file(fp, meta)

        assert result.name == "original.mp3"

    def test_all_illegal_artist_keeps_original_name(self, tmp_path: Path) -> None:
        fp = tmp_path / "original.mp3"
        make_silent(fp)

        meta = EnrichedMetadata(artist="///", title="Valid Title")
        result = tag_file(fp, meta)

        assert result.name == "original.mp3"
