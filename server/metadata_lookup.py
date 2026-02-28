from __future__ import annotations

import asyncio
import re
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

import musicbrainzngs  # type: ignore[import-untyped]
import pylast

_REMIX_RE = re.compile(
    r"\(([^)]+?)\s+(remix|edit|bootleg|vip|flip)\)",
    re.IGNORECASE,
)

_useragent_set = False


def _ensure_useragent(user_agent: str) -> None:
    global _useragent_set
    if not _useragent_set:
        app, version = user_agent.split("/", 1) if "/" in user_agent else (user_agent, "1.0")
        musicbrainzngs.set_useragent(app, version)
        _useragent_set = True


@dataclass
class MetadataCandidate:
    source: str
    artist: str
    title: str
    album: str | None = None
    label: str | None = None
    year: int | None = None
    genre_tags: list[str] = field(default_factory=list)
    match_score: float = 0.0
    musicbrainz_id: str | None = None
    cover_art_url: str | None = None


def search_musicbrainz(
    artist: str,
    title: str,
    limit: int = 5,
    user_agent: str = "dj-kompanion/1.0",
) -> list[MetadataCandidate]:
    """Search MusicBrainz for recordings matching artist and title.

    Never raises — returns empty list on any error.
    """
    try:
        _ensure_useragent(user_agent)
        result = musicbrainzngs.search_recordings(artist=artist, recording=title, limit=limit)
    except Exception:
        return []

    candidates: list[MetadataCandidate] = []

    for rec in result.get("recording-list", []):
        try:
            candidate = _parse_recording(rec)
            candidates.append(candidate)
        except Exception:
            continue

    return candidates


def _parse_recording(rec: dict[object, object]) -> MetadataCandidate:
    mbid = str(rec.get("id", ""))
    title = str(rec.get("title", ""))
    score_raw = rec.get("ext:score", "0")
    match_score = float(str(score_raw)) if score_raw else 0.0

    artist_credit = rec.get("artist-credit", [])
    artist = ""
    if isinstance(artist_credit, list) and artist_credit:
        first = artist_credit[0]
        if isinstance(first, dict):
            artist_info = first.get("artist", {})
            if isinstance(artist_info, dict):
                artist = str(artist_info.get("name", ""))

    tag_list = rec.get("tag-list", [])
    genre_tags: list[str] = []
    if isinstance(tag_list, list):
        for t in tag_list:
            if isinstance(t, dict) and "name" in t:
                genre_tags.append(str(t["name"]))

    release_list = rec.get("release-list", [])
    album: str | None = None
    year: int | None = None
    label: str | None = None
    cover_art_url: str | None = None
    release_id: str | None = None

    if isinstance(release_list, list) and release_list:
        first_release = release_list[0]
        if isinstance(first_release, dict):
            release_id = str(first_release.get("id", "")) or None
            album_raw = first_release.get("title")
            album = str(album_raw) if album_raw else None
            date_raw = first_release.get("date", "")
            if date_raw and isinstance(date_raw, str) and len(date_raw) >= 4:
                try:
                    year = int(date_raw[:4])
                except ValueError:
                    year = None

    if release_id:
        cover_art_url = f"https://coverartarchive.org/release/{release_id}/front-250"
        try:
            release_result = musicbrainzngs.get_release_by_id(release_id, includes=["labels"])
            release = release_result.get("release", {})
            label_info_list = release.get("label-info-list", [])
            if isinstance(label_info_list, list) and label_info_list:
                label_info = label_info_list[0]
                if isinstance(label_info, dict):
                    label_obj = label_info.get("label", {})
                    if isinstance(label_obj, dict):
                        label_name = label_obj.get("name")
                        label = str(label_name) if label_name else None
        except Exception:
            label = None

    return MetadataCandidate(
        source="musicbrainz",
        artist=artist,
        title=title,
        album=album,
        label=label,
        year=year,
        genre_tags=genre_tags,
        match_score=match_score,
        musicbrainz_id=mbid or None,
        cover_art_url=cover_art_url,
    )


def search_lastfm(
    artist: str,
    title: str,
    api_key: str = "",
) -> list[MetadataCandidate]:
    """Look up a track on Last.fm by artist and title, returning genre tags.

    Never raises — returns empty list on any error or if api_key is empty.
    """
    if not api_key:
        return []

    try:
        network = pylast.LastFMNetwork(api_key=api_key)
        track = network.get_track(artist, title)

        top_tags = track.get_top_tags()
        genre_tags: list[str] = [tag_item.item.name for tag_item in top_tags]

        album_obj = track.get_album()
        album: str | None = album_obj.get_name() if album_obj is not None else None

        return [
            MetadataCandidate(
                source="lastfm",
                artist=artist,
                title=title,
                album=album,
                genre_tags=genre_tags,
                match_score=100.0,
            )
        ]
    except Exception:
        return []


def _parse_remix(title: str) -> tuple[str, str | None]:
    """Extract base title and remix query from a title.

    Returns (base_title, remix_query) where remix_query is None if not a remix.
    Example: "Rumble (Fred again.. Remix)" -> ("Rumble", "Rumble Fred again.. Remix")
    """
    match = _REMIX_RE.search(title)
    if not match:
        return title, None
    base = title[: match.start()].strip()
    remix_query = f"{base} {match.group(1)} {match.group(2)}"
    return base, remix_query


async def search_metadata(
    artist: str,
    title: str,
    lastfm_api_key: str = "",
    search_limit: int = 5,
    user_agent: str = "dj-kompanion/1.0",
) -> list[MetadataCandidate]:
    """Run MusicBrainz and Last.fm searches in parallel and combine results.

    If the title contains a remix suffix, also runs a second MusicBrainz search
    with the remix query, deduplicating by musicbrainz_id. Returns candidates
    sorted by match_score descending. Never raises — returns empty list on failure.
    """
    try:
        base_title, remix_query = _parse_remix(title)

        tasks: list[Coroutine[Any, Any, list[MetadataCandidate]]] = [
            asyncio.to_thread(
                search_musicbrainz, artist, base_title, search_limit, user_agent
            ),
            asyncio.to_thread(search_lastfm, artist, title, lastfm_api_key),
        ]
        if remix_query is not None:
            tasks.append(
                asyncio.to_thread(
                    search_musicbrainz, artist, remix_query, search_limit, user_agent
                )
            )

        results = await asyncio.gather(*tasks)

        all_candidates: list[MetadataCandidate] = []
        seen_mbids: set[str] = set()

        for batch in results:
            for candidate in batch:
                mbid = candidate.musicbrainz_id
                if mbid is not None:
                    if mbid in seen_mbids:
                        continue
                    seen_mbids.add(mbid)
                all_candidates.append(candidate)

        all_candidates.sort(key=lambda c: c.match_score, reverse=True)
        return all_candidates
    except Exception:
        return []
