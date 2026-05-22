from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from server.models import ProviderError, RecommendationSource, RecommendedDownloadFilters

if TYPE_CHECKING:
    from collections.abc import Mapping

    from server.recommendations.open_data_clients import (
        AcousticBrainzClient,
        ListenBrainzClient,
        MusicBrainzClient,
    )


@dataclass
class ProviderSeed:
    filepath: str
    artist: str
    title: str
    recording_mbid: str | None = None
    bpm: float | None = None
    key: str | None = None
    key_camelot: str | None = None
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ProviderCandidate:
    artist: str
    title: str
    recording_mbid: str | None = None
    release_mbid: str | None = None
    source_urls: dict[str, str] = field(default_factory=dict)
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    bpm: float | None = None
    key: str | None = None
    key_camelot: str | None = None
    source: RecommendationSource = RecommendationSource.musicbrainz
    sources: list[RecommendationSource] = field(default_factory=list)
    source_confidence: float = 0.0
    metadata_similarity: float = 0.0


@dataclass
class ProviderResult:
    candidates: list[ProviderCandidate]
    errors: list[ProviderError]


class RecommendationProvider(Protocol):
    source: RecommendationSource

    def fetch(
        self,
        seed: ProviderSeed,
        filters: RecommendedDownloadFilters,
        limit: int,
    ) -> ProviderResult: ...


def _artist_credit_name(recording: Mapping[str, object]) -> str:
    credits = recording.get("artist-credit")
    if isinstance(credits, list):
        names = []
        for credit in credits:
            if isinstance(credit, dict):
                artist = credit.get("artist")
                if isinstance(artist, dict) and isinstance(artist.get("name"), str):
                    names.append(artist["name"])
                elif isinstance(credit.get("name"), str):
                    names.append(credit["name"])
        if names:
            return " & ".join(names)
    title = recording.get("title")
    return str(title or "Unknown Artist")


def _names_from_items(recording: Mapping[str, object], field_name: str) -> list[str]:
    items = recording.get(field_name)
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


class MusicBrainzProvider:
    source = RecommendationSource.musicbrainz

    def __init__(self, client: MusicBrainzClient) -> None:
        self.client = client

    def fetch(
        self,
        seed: ProviderSeed,
        filters: RecommendedDownloadFilters,
        limit: int,
    ) -> ProviderResult:
        del filters
        try:
            payload = self.client.search_recordings(seed.artist, seed.title, limit=limit)
        except Exception as exc:
            return ProviderResult(
                candidates=[],
                errors=[ProviderError(source=self.source, error=str(exc), retryable=True)],
            )
        recordings = payload.get("recordings")
        if not isinstance(recordings, list):
            return ProviderResult(candidates=[], errors=[])
        candidates: list[ProviderCandidate] = []
        for item in recordings[:limit]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if not isinstance(title, str):
                continue
            mbid = item.get("id") if isinstance(item.get("id"), str) else None
            releases = item.get("releases")
            release_mbid = None
            if isinstance(releases, list) and releases and isinstance(releases[0], dict):
                value = releases[0].get("id")
                release_mbid = value if isinstance(value, str) else None
            candidates.append(
                ProviderCandidate(
                    artist=_artist_credit_name(item),
                    title=title,
                    recording_mbid=mbid,
                    release_mbid=release_mbid,
                    source_urls={
                        "musicbrainz": f"https://musicbrainz.org/recording/{mbid}"
                    }
                    if mbid
                    else {},
                    genres=_names_from_items(item, "genres"),
                    tags=_names_from_items(item, "tags"),
                    source=self.source,
                    source_confidence=0.8 if mbid else 0.6,
                    metadata_similarity=0.75,
                )
            )
        return ProviderResult(candidates=candidates, errors=[])


class ListenBrainzProvider:
    source = RecommendationSource.listenbrainz

    def __init__(self, client: ListenBrainzClient) -> None:
        self.client = client

    def fetch(
        self,
        seed: ProviderSeed,
        filters: RecommendedDownloadFilters,
        limit: int,
    ) -> ProviderResult:
        del filters
        try:
            if seed.recording_mbid:
                payload = self.client.similar_recordings(seed.recording_mbid, limit=limit)
            else:
                payload = self.client.metadata_lookup(seed.artist, seed.title)
        except Exception as exc:
            return ProviderResult(
                candidates=[],
                errors=[ProviderError(source=self.source, error=str(exc), retryable=True)],
            )
        recordings = payload.get("recordings") or payload.get("payload") or []
        if isinstance(recordings, dict):
            recordings = recordings.get("recordings", [])
        if not isinstance(recordings, list):
            return ProviderResult(candidates=[], errors=[])
        candidates: list[ProviderCandidate] = []
        for item in recordings[:limit]:
            if not isinstance(item, dict):
                continue
            title_value = item.get("recording_name") or item.get("track_name") or item.get("title")
            artist_value = item.get("artist_name") or item.get("artist_credit_name")
            if not isinstance(title_value, str) or not isinstance(artist_value, str):
                continue
            mbid_value = item.get("recording_mbid") or item.get("recording_msid")
            mbid = mbid_value if isinstance(mbid_value, str) else None
            release_mbid_value = item.get("release_mbid")
            release_mbid = release_mbid_value if isinstance(release_mbid_value, str) else None
            candidates.append(
                ProviderCandidate(
                    artist=artist_value,
                    title=title_value,
                    recording_mbid=mbid,
                    release_mbid=release_mbid,
                    source_urls={"listenbrainz": "https://listenbrainz.org/"},
                    source=self.source,
                    source_confidence=0.7 if mbid else 0.45,
                    metadata_similarity=0.65,
                )
            )
        return ProviderResult(candidates=candidates, errors=[])


class AcousticBrainzProvider:
    source = RecommendationSource.acousticbrainz

    def __init__(self, client: AcousticBrainzClient) -> None:
        self.client = client

    def fetch(
        self,
        seed: ProviderSeed,
        filters: RecommendedDownloadFilters,
        limit: int,
    ) -> ProviderResult:
        del filters, limit
        if not seed.recording_mbid:
            return ProviderResult(candidates=[], errors=[])
        try:
            count = self.client.count(seed.recording_mbid)
            if count <= 0:
                return ProviderResult(candidates=[], errors=[])
            low_level = self.client.low_level(seed.recording_mbid)
            high_level = self.client.high_level(seed.recording_mbid)
        except FileNotFoundError:
            return ProviderResult(candidates=[], errors=[])
        except Exception as exc:
            return ProviderResult(
                candidates=[],
                errors=[ProviderError(source=self.source, error=str(exc), retryable=True)],
            )
        key = _acoustic_key(low_level)
        return ProviderResult(
            candidates=[
                ProviderCandidate(
                    artist=seed.artist,
                    title=seed.title,
                    recording_mbid=seed.recording_mbid,
                    source_urls={
                        "acousticbrainz": f"https://acousticbrainz.org/{seed.recording_mbid}"
                    },
                    genres=_acoustic_genres(high_level),
                    bpm=_acoustic_bpm(low_level),
                    key=key,
                    source=self.source,
                    source_confidence=0.25,
                    metadata_similarity=0.5,
                )
            ],
            errors=[],
        )


def _acoustic_bpm(payload: Mapping[str, object]) -> float | None:
    rhythm = payload.get("rhythm")
    if isinstance(rhythm, dict) and isinstance(rhythm.get("bpm"), int | float):
        return float(rhythm["bpm"])
    return None


def _acoustic_key(payload: Mapping[str, object]) -> str | None:
    tonal = payload.get("tonal")
    if not isinstance(tonal, dict):
        return None
    key = tonal.get("key_key")
    scale = tonal.get("key_scale")
    if isinstance(key, str) and isinstance(scale, str):
        return f"{key} {scale}"
    return None


def _acoustic_genres(payload: Mapping[str, object]) -> list[str]:
    genres: list[str] = []
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            genres.append(value["value"])
    return genres
