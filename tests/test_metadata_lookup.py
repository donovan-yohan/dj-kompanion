from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import musicbrainzngs

from server.metadata_lookup import (
    MetadataCandidate,
    search_lastfm,
    search_metadata,
    search_musicbrainz,
)


def _make_recording(
    mbid: str = "rec-123",
    title: str = "Rumble",
    score: str = "95",
    artist_name: str = "Skrillex",
    release_id: str = "rel-456",
    release_title: str = "Quest for Fire",
    release_date: str = "2023-02-17",
    tags: list[dict[str, str]] | None = None,
) -> dict[object, object]:
    rec: dict[object, object] = {
        "id": mbid,
        "title": title,
        "ext:score": score,
        "artist-credit": [{"artist": {"id": "artist-1", "name": artist_name}}],
        "release-list": [
            {
                "id": release_id,
                "title": release_title,
                "date": release_date,
            }
        ],
    }
    if tags is not None:
        rec["tag-list"] = tags
    return rec


def _make_release_result(label_name: str = "OWSLA") -> dict[object, object]:
    return {
        "release": {
            "id": "rel-456",
            "title": "Quest for Fire",
            "label-info-list": [{"label": {"name": label_name}}],
        }
    }


# --- test_search_musicbrainz_returns_candidates ---


def test_search_musicbrainz_returns_candidates() -> None:
    recording = _make_recording(tags=[{"name": "electronic"}, {"name": "dubstep"}])
    search_result = {"recording-list": [recording]}
    release_result = _make_release_result()

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", return_value=search_result),
        patch("musicbrainzngs.get_release_by_id", return_value=release_result),
    ):
        candidates = search_musicbrainz("Skrillex", "Rumble")

    assert len(candidates) == 1
    c = candidates[0]
    assert isinstance(c, MetadataCandidate)
    assert c.source == "musicbrainz"
    assert c.artist == "Skrillex"
    assert c.title == "Rumble"
    assert c.album == "Quest for Fire"
    assert c.year == 2023
    assert c.label == "OWSLA"
    assert c.genre_tags == ["electronic", "dubstep"]
    assert c.match_score == 95.0
    assert c.musicbrainz_id == "rec-123"
    assert c.cover_art_url == "https://coverartarchive.org/release/rel-456/front-250"


# --- test_search_musicbrainz_handles_api_error ---


def test_search_musicbrainz_handles_api_error() -> None:
    with (
        patch("musicbrainzngs.set_useragent"),
        patch(
            "musicbrainzngs.search_recordings",
            side_effect=musicbrainzngs.WebServiceError("503"),
        ),
    ):
        result = search_musicbrainz("Skrillex", "Rumble")

    assert result == []


def test_search_musicbrainz_handles_generic_exception() -> None:
    with (
        patch("musicbrainzngs.set_useragent"),
        patch(
            "musicbrainzngs.search_recordings",
            side_effect=Exception("unexpected"),
        ),
    ):
        result = search_musicbrainz("Skrillex", "Rumble")

    assert result == []


# --- test_search_musicbrainz_handles_missing_fields ---


def test_search_musicbrainz_handles_missing_release_list() -> None:
    """Recording with no release-list: album/year/label/cover_art_url should be None."""
    recording: dict[object, object] = {
        "id": "rec-999",
        "title": "Unknown Track",
        "ext:score": "80",
        "artist-credit": [{"artist": {"id": "artist-1", "name": "Some Artist"}}],
    }
    search_result = {"recording-list": [recording]}

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", return_value=search_result),
    ):
        candidates = search_musicbrainz("Some Artist", "Unknown Track")

    assert len(candidates) == 1
    c = candidates[0]
    assert c.album is None
    assert c.year is None
    assert c.label is None
    assert c.cover_art_url is None
    assert c.genre_tags == []


def test_search_musicbrainz_handles_missing_tag_list() -> None:
    """Recording with no tag-list: genre_tags should default to []."""
    recording = _make_recording()  # no tags kwarg = no tag-list
    search_result = {"recording-list": [recording]}
    release_result = _make_release_result()

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", return_value=search_result),
        patch("musicbrainzngs.get_release_by_id", return_value=release_result),
    ):
        candidates = search_musicbrainz("Skrillex", "Rumble")

    assert candidates[0].genre_tags == []


def test_search_musicbrainz_handles_get_release_error() -> None:
    """If get_release_by_id fails, label should be None but rest of fields still populated."""
    recording = _make_recording(tags=[{"name": "electronic"}])
    search_result = {"recording-list": [recording]}

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", return_value=search_result),
        patch(
            "musicbrainzngs.get_release_by_id",
            side_effect=musicbrainzngs.WebServiceError("404"),
        ),
    ):
        candidates = search_musicbrainz("Skrillex", "Rumble")

    assert len(candidates) == 1
    c = candidates[0]
    assert c.label is None
    assert c.album == "Quest for Fire"
    assert c.artist == "Skrillex"


def test_search_musicbrainz_handles_partial_date() -> None:
    """Date with only year component (YYYY) should parse correctly."""
    recording = _make_recording(release_date="2023")
    search_result = {"recording-list": [recording]}
    release_result = _make_release_result()

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", return_value=search_result),
        patch("musicbrainzngs.get_release_by_id", return_value=release_result),
    ):
        candidates = search_musicbrainz("Skrillex", "Rumble")

    assert candidates[0].year == 2023


def test_search_musicbrainz_returns_empty_list_on_empty_recording_list() -> None:
    search_result: dict[str, list[object]] = {"recording-list": []}

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", return_value=search_result),
    ):
        result = search_musicbrainz("Nobody", "Nothing")

    assert result == []


def test_search_musicbrainz_passes_limit_to_api() -> None:
    search_result: dict[str, list[object]] = {"recording-list": []}
    captured: list[dict[object, object]] = []

    def fake_search(**kwargs: object) -> dict[str, list[object]]:
        captured.append(dict(kwargs))  # type: ignore[arg-type]
        return search_result

    with (
        patch("musicbrainzngs.set_useragent"),
        patch("musicbrainzngs.search_recordings", side_effect=fake_search),
    ):
        search_musicbrainz("Artist", "Title", limit=3)

    assert captured[0]["limit"] == 3


# ---------------------------------------------------------------------------
# Last.fm tests
# ---------------------------------------------------------------------------


def _make_tag_item(name: str, weight: int = 100) -> MagicMock:
    tag_item = MagicMock()
    tag_item.item.name = name
    tag_item.weight = weight
    return tag_item


def test_search_lastfm_returns_candidates() -> None:
    mock_network = MagicMock()
    mock_track = MagicMock()
    mock_album = MagicMock()

    mock_album.get_name.return_value = "Quest for Fire"
    mock_track.get_top_tags.return_value = [
        _make_tag_item("dubstep", 100),
        _make_tag_item("electronic", 80),
    ]
    mock_track.get_album.return_value = mock_album
    mock_network.get_track.return_value = mock_track

    with patch("pylast.LastFMNetwork", return_value=mock_network):
        candidates = search_lastfm("Skrillex", "Rumble", api_key="fake-key")

    assert len(candidates) == 1
    c = candidates[0]
    assert isinstance(c, MetadataCandidate)
    assert c.source == "lastfm"
    assert c.artist == "Skrillex"
    assert c.title == "Rumble"
    assert c.album == "Quest for Fire"
    assert c.genre_tags == ["dubstep", "electronic"]
    assert c.match_score == 100.0


def test_search_lastfm_skipped_without_api_key() -> None:
    result = search_lastfm("Skrillex", "Rumble", api_key="")
    assert result == []


def test_search_lastfm_handles_api_error() -> None:
    with patch("pylast.LastFMNetwork", side_effect=Exception("API error")):
        result = search_lastfm("Skrillex", "Rumble", api_key="fake-key")

    assert result == []


def test_search_lastfm_handles_no_album() -> None:
    mock_network = MagicMock()
    mock_track = MagicMock()

    mock_track.get_top_tags.return_value = [_make_tag_item("electronic", 100)]
    mock_track.get_album.return_value = None
    mock_network.get_track.return_value = mock_track

    with patch("pylast.LastFMNetwork", return_value=mock_network):
        candidates = search_lastfm("Skrillex", "Rumble", api_key="fake-key")

    assert len(candidates) == 1
    assert candidates[0].album is None


# ---------------------------------------------------------------------------
# search_metadata orchestrator tests
# ---------------------------------------------------------------------------


def _make_candidate(
    source: str = "musicbrainz",
    mbid: str | None = "rec-1",
    match_score: float = 90.0,
) -> MetadataCandidate:
    return MetadataCandidate(
        source=source,
        artist="Skrillex",
        title="Rumble",
        match_score=match_score,
        musicbrainz_id=mbid,
    )


def test_search_metadata_combines_sources() -> None:
    mb_candidate = _make_candidate(source="musicbrainz", mbid="rec-1", match_score=90.0)
    lfm_candidate = _make_candidate(source="lastfm", mbid=None, match_score=100.0)

    with (
        patch(
            "server.metadata_lookup.search_musicbrainz",
            return_value=[mb_candidate],
        ),
        patch(
            "server.metadata_lookup.search_lastfm",
            return_value=[lfm_candidate],
        ),
    ):
        result = asyncio.run(search_metadata("Skrillex", "Rumble", lastfm_api_key="fake-key"))

    assert len(result) == 2
    # sorted by match_score descending
    assert result[0].source == "lastfm"
    assert result[0].match_score == 100.0
    assert result[1].source == "musicbrainz"
    assert result[1].match_score == 90.0


def test_search_metadata_handles_remix_title() -> None:
    base_candidate = _make_candidate(source="musicbrainz", mbid="rec-base", match_score=80.0)
    remix_candidate = _make_candidate(source="musicbrainz", mbid="rec-remix", match_score=95.0)

    call_args: list[tuple[object, ...]] = []

    def fake_search_musicbrainz(
        artist: str, title: str, *args: object, **kwargs: object
    ) -> list[MetadataCandidate]:
        call_args.append((artist, title))
        if "Fred again" in title:
            return [remix_candidate]
        return [base_candidate]

    with (
        patch(
            "server.metadata_lookup.search_musicbrainz",
            side_effect=fake_search_musicbrainz,
        ),
        patch(
            "server.metadata_lookup.search_lastfm",
            return_value=[],
        ),
    ):
        result = asyncio.run(search_metadata("Skrillex", "Rumble (Fred again.. Remix)"))

    # Should have called MusicBrainz twice (base + remix query)
    mb_calls = [args for args in call_args]
    assert len(mb_calls) == 2

    # Both unique candidates present
    mbids = {c.musicbrainz_id for c in result}
    assert "rec-base" in mbids
    assert "rec-remix" in mbids

    # Sorted by score: remix (95) before base (80)
    assert result[0].musicbrainz_id == "rec-remix"


def test_search_metadata_deduplicates_by_mbid() -> None:
    duplicate = _make_candidate(source="musicbrainz", mbid="rec-same", match_score=90.0)

    with (
        patch(
            "server.metadata_lookup.search_musicbrainz",
            return_value=[duplicate],
        ),
        patch(
            "server.metadata_lookup.search_lastfm",
            return_value=[],
        ),
    ):
        # Use a remix title so MB is called twice, both returning the same mbid
        result = asyncio.run(search_metadata("Artist", "Song (Someone Remix)"))

    # Only one copy of the duplicate mbid
    assert len([c for c in result if c.musicbrainz_id == "rec-same"]) == 1


def test_search_metadata_returns_empty_on_all_failures() -> None:
    with (
        patch(
            "server.metadata_lookup.search_musicbrainz",
            return_value=[],
        ),
        patch(
            "server.metadata_lookup.search_lastfm",
            return_value=[],
        ),
    ):
        result = asyncio.run(search_metadata("Nobody", "Nothing"))

    assert result == []
