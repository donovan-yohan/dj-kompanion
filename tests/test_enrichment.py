from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

from server.enrichment import basic_enrich, enrich_metadata, is_claude_available
from server.models import EnrichedMetadata, RawMetadata


def make_raw(
    title: str = "Test Artist - Test Title",
    uploader: str | None = "Test Channel",
    source_url: str = "https://youtube.com/watch?v=test",
) -> RawMetadata:
    return RawMetadata(
        title=title,
        uploader=uploader,
        duration=180,
        upload_date="20230101",
        description=None,
        tags=[],
        source_url=source_url,
    )


def make_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    mock: subprocess.CompletedProcess[str] = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


def claude_json(
    artist: str = "Test Artist",
    title: str = "Test Title",
    genre: str | None = None,
    year: int | None = None,
    energy: int | None = None,
    comment: str = "https://youtube.com/watch?v=test",
) -> str:
    data: dict[str, Any] = {
        "artist": artist,
        "title": title,
        "genre": genre,
        "year": year,
        "label": None,
        "energy": energy,
        "bpm": None,
        "key": None,
        "comment": comment,
    }
    return json.dumps(data)


# --- basic_enrich ---


def test_basic_enrich_dash_separator() -> None:
    raw = make_raw(title="DJ Snake - Turn Down for What (Official Video) [HD]")
    result = basic_enrich(raw)
    assert result.artist == "DJ Snake"
    assert result.title == "Turn Down for What"


def test_basic_enrich_no_separator_uses_uploader() -> None:
    raw = make_raw(title="Turn Down for What", uploader="DJ Snake VEVO")
    result = basic_enrich(raw)
    assert result.artist == "DJ Snake VEVO"
    assert result.title == "Turn Down for What"


def test_basic_enrich_no_separator_no_uploader() -> None:
    raw = make_raw(title="Turn Down for What", uploader=None)
    result = basic_enrich(raw)
    assert result.artist == "Unknown"
    assert result.title == "Turn Down for What"


def test_basic_enrich_dots_and_ampersand() -> None:
    raw = make_raw(title="Fred again.. & Skrillex - Baby again..")
    result = basic_enrich(raw)
    assert result.artist == "Fred again.. & Skrillex"
    assert result.title == "Baby again.."


def test_basic_enrich_pipe_separator() -> None:
    raw = make_raw(title="Bicep | GLUE (Official Video)")
    result = basic_enrich(raw)
    assert result.artist == "Bicep"
    assert result.title == "GLUE"


def test_basic_enrich_double_slash_separator() -> None:
    raw = make_raw(title="Bonobo // Kong")
    result = basic_enrich(raw)
    assert result.artist == "Bonobo"
    assert result.title == "Kong"


def test_basic_enrich_strips_official_audio() -> None:
    raw = make_raw(title="Artist - Song (Official Audio)")
    result = basic_enrich(raw)
    assert result.title == "Song"


def test_basic_enrich_sets_comment() -> None:
    url = "https://youtube.com/watch?v=abc123"
    raw = make_raw(source_url=url)
    result = basic_enrich(raw)
    assert result.comment == url


def test_basic_enrich_returns_enriched_metadata() -> None:
    raw = make_raw()
    result = basic_enrich(raw)
    assert isinstance(result, EnrichedMetadata)
    assert result.genre is None
    assert result.year is None
    assert result.bpm is None


# --- is_claude_available ---


def test_is_claude_available_true() -> None:
    with patch("server.enrichment.subprocess.run") as mock_run:
        mock_run.return_value = make_process("", returncode=0)
        result = asyncio.run(is_claude_available())
    assert result is True


def test_is_claude_available_false_nonzero_exit() -> None:
    with patch("server.enrichment.subprocess.run") as mock_run:
        mock_run.return_value = make_process("", returncode=1)
        result = asyncio.run(is_claude_available())
    assert result is False


def test_is_claude_available_not_found() -> None:
    with patch("server.enrichment.subprocess.run", side_effect=FileNotFoundError()):
        result = asyncio.run(is_claude_available())
    assert result is False


def test_is_claude_available_timeout() -> None:
    with patch(
        "server.enrichment.subprocess.run",
        side_effect=subprocess.TimeoutExpired("claude", 5),
    ):
        result = asyncio.run(is_claude_available())
    assert result is False


# --- enrich_metadata ---


def _fake_run_success(response: str) -> Any:
    """Returns a side_effect function that succeeds for --version and enrichment."""

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        return make_process(response, returncode=0)

    return fake_run


def test_enrich_metadata_returns_valid_enriched_metadata() -> None:
    raw = make_raw()
    response = claude_json(artist="DJ Snake", title="Turn Down for What", genre="EDM")

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(enrich_metadata(raw))

    assert isinstance(result, EnrichedMetadata)
    assert result.artist == "DJ Snake"
    assert result.title == "Turn Down for What"
    assert result.genre == "EDM"
    assert result.comment == raw.source_url


def test_enrich_metadata_with_year_and_energy() -> None:
    raw = make_raw()
    response = claude_json(artist="Bicep", title="GLUE", year=2017, energy=7)

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(enrich_metadata(raw))

    assert result.year == 2017
    assert result.energy == 7
    assert result.bpm is None
    assert result.key is None


def test_enrich_metadata_fallback_when_claude_unavailable() -> None:
    raw = make_raw(title="DJ Snake - Turn Down for What")

    with patch("server.enrichment.subprocess.run", side_effect=FileNotFoundError()):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "DJ Snake"
    assert result.title == "Turn Down for What"


def test_enrich_metadata_fallback_on_invalid_json() -> None:
    raw = make_raw(title="DJ Snake - Turn Down for What")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        return make_process("not valid json at all", returncode=0)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "DJ Snake"
    assert result.title == "Turn Down for What"


def test_enrich_metadata_fallback_on_timeout() -> None:
    raw = make_raw(title="DJ Snake - Turn Down for What")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        raise subprocess.TimeoutExpired("claude", 30)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "DJ Snake"
    assert result.title == "Turn Down for What"


def test_enrich_metadata_fallback_on_nonzero_exit() -> None:
    raw = make_raw(title="DJ Snake - Turn Down for What")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        return make_process("error output", returncode=1)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "DJ Snake"
    assert result.title == "Turn Down for What"


def test_enrich_metadata_handles_json_envelope() -> None:
    """Test that --output-format json envelope is unwrapped correctly."""
    raw = make_raw()
    inner = claude_json(artist="Bicep", title="GLUE")
    envelope = json.dumps({"type": "result", "subtype": "success", "result": inner})

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(envelope)):
        result = asyncio.run(enrich_metadata(raw))

    assert result.artist == "Bicep"
    assert result.title == "GLUE"


def test_enrich_metadata_uses_custom_model() -> None:
    """Test that the model parameter is passed to the claude command."""
    raw = make_raw()
    response = claude_json()
    captured_cmd: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_cmd.append(cmd)
        if "--version" in cmd:
            return make_process("", returncode=0)
        return make_process(response, returncode=0)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        asyncio.run(enrich_metadata(raw, model="sonnet"))

    enrichment_cmd = [c for c in captured_cmd if "--version" not in c][0]
    assert "sonnet" in enrichment_cmd


# --- merge_metadata ---


from server.enrichment import merge_metadata


def test_merge_user_edited_wins_over_claude() -> None:
    user = EnrichedMetadata(artist="My Edit", title="My Title", genre="Pop")
    claude = EnrichedMetadata(artist="Claude Artist", title="Claude Title", genre="EDM")
    result = merge_metadata(user, claude, user_edited_fields=["artist", "genre"])
    assert result.artist == "My Edit"  # user edited
    assert result.genre == "Pop"  # user edited
    assert result.title == "Claude Title"  # not edited, Claude wins


def test_merge_claude_fills_non_edited_nulls() -> None:
    user = EnrichedMetadata(artist="Artist", title="Title", genre=None)
    claude = EnrichedMetadata(artist="Artist", title="Title", genre="House", year=2024, energy=7)
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.genre == "House"
    assert result.year == 2024
    assert result.energy == 7


def test_merge_basic_fallback_for_claude_null() -> None:
    user = EnrichedMetadata(artist="Artist", title="Title", energy=5)
    claude = EnrichedMetadata(artist="Artist", title="Title", energy=None)
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.energy == 5  # Claude null, fall back to user/basic value


def test_merge_none_claude_returns_basic() -> None:
    user = EnrichedMetadata(artist="Artist", title="Title", genre="Pop")
    result = merge_metadata(user, None, user_edited_fields=[])
    assert result.artist == "Artist"
    assert result.genre == "Pop"


def test_merge_empty_edited_uses_all_claude() -> None:
    user = EnrichedMetadata(artist="Basic", title="Basic")
    claude = EnrichedMetadata(
        artist="Claude", title="Better Title", genre="Techno", year=2023, energy=8
    )
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.artist == "Claude"
    assert result.title == "Better Title"
    assert result.genre == "Techno"
    assert result.year == 2023
    assert result.energy == 8


def test_merge_preserves_comment() -> None:
    user = EnrichedMetadata(artist="A", title="T", comment="https://example.com")
    claude = EnrichedMetadata(artist="A", title="T", comment="https://other.com")
    result = merge_metadata(user, claude, user_edited_fields=[])
    assert result.comment == "https://example.com"  # user's comment always preserved


# --- try_enrich_metadata ---


from server.enrichment import try_enrich_metadata


def test_try_enrich_returns_none_when_unavailable() -> None:
    raw = make_raw()
    with patch("server.enrichment.subprocess.run", side_effect=FileNotFoundError()):
        result = asyncio.run(try_enrich_metadata(raw))
    assert result is None


def test_try_enrich_returns_none_on_timeout() -> None:
    raw = make_raw()

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        raise subprocess.TimeoutExpired("claude", 30)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(try_enrich_metadata(raw))
    assert result is None


def test_try_enrich_returns_metadata_on_success() -> None:
    raw = make_raw()
    response = claude_json(artist="Bicep", title="GLUE", genre="Electronic")

    with patch("server.enrichment.subprocess.run", side_effect=_fake_run_success(response)):
        result = asyncio.run(try_enrich_metadata(raw))

    assert result is not None
    assert result.artist == "Bicep"
    assert result.genre == "Electronic"


def test_try_enrich_returns_none_on_invalid_json() -> None:
    raw = make_raw()

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return make_process("", returncode=0)
        return make_process("not json", returncode=0)

    with patch("server.enrichment.subprocess.run", side_effect=fake_run):
        result = asyncio.run(try_enrich_metadata(raw))
    assert result is None
