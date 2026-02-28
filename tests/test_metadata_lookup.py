from __future__ import annotations

from unittest.mock import MagicMock, patch

import musicbrainzngs
import pytest

from server.metadata_lookup import MetadataCandidate, search_musicbrainz


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
