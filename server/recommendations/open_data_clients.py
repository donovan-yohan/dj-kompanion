from __future__ import annotations

import copy
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Mapping

JsonObject = dict[str, Any]
DEFAULT_SIMILAR_RECORDINGS_ALGORITHM = "session_based_days_180_session_300_contribution_5_threshold_15_limit_50_skip_30"


class MusicBrainzClient:
    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://musicbrainz.org/ws/2",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0
        self._cache: dict[tuple[str, tuple[tuple[str, str | int | float], ...]], JsonObject] = {}
        self._lock = threading.RLock()
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )

    def _request(self, path: str, params: Mapping[str, str | int | float]) -> JsonObject:
        cache_key = (path, tuple(sorted(params.items())))
        with self._lock:
            if cache_key in self._cache:
                return copy.deepcopy(self._cache[cache_key])
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
            response = self._client.get(path, params=params)
            self._last_request_at = time.monotonic()
            response.raise_for_status()
            data = response.json()
            result = data if isinstance(data, dict) else {}
            self._cache[cache_key] = result
            return copy.deepcopy(result)

    def search_recordings(self, artist: str, title: str, limit: int = 10) -> JsonObject:
        query = f'artist:"{artist}" AND recording:"{title}"'
        return self._request(
            "/recording",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "inc": "artist-credits+releases+tags+genres+isrcs",
            },
        )

    def recording(self, recording_mbid: str) -> JsonObject:
        return self._request(
            f"/recording/{recording_mbid}",
            {
                "fmt": "json",
                "inc": "artists+releases+isrcs+tags+genres+artist-rels+recording-rels+release-rels+url-rels+work-rels",
            },
        )

    def by_isrc(self, isrc: str) -> JsonObject:
        return self._request(
            f"/isrc/{isrc}",
            {"fmt": "json", "inc": "artists+releases"},
        )


class ListenBrainzClient:
    def __init__(
        self,
        base_url: str = "https://api.listenbrainz.org/1",
        labs_base_url: str = "https://labs.api.listenbrainz.org",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        similar_recordings_algorithm: str = DEFAULT_SIMILAR_RECORDINGS_ALGORITHM,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.labs_base_url = labs_base_url.rstrip("/")
        self.similar_recordings_algorithm = similar_recordings_algorithm
        self._cache: dict[tuple[str, tuple[tuple[str, str | int | float], ...]], JsonObject] = {}
        self._lock = threading.RLock()
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def _get(self, url: str, params: Mapping[str, str | int | float] | None = None) -> JsonObject:
        request_params = params or {}
        cache_key = (url, tuple(sorted(request_params.items())))
        with self._lock:
            if cache_key in self._cache:
                return copy.deepcopy(self._cache[cache_key])
            response = self._client.get(url, params=request_params)
            response.raise_for_status()
            data = response.json()
            result = data if isinstance(data, dict) else {}
            self._cache[cache_key] = result
            return copy.deepcopy(result)

    def similar_recordings(self, recording_mbid: str, limit: int = 25) -> JsonObject:
        url = f"{self.labs_base_url}/similar-recordings/json"
        params = {
            "recording_mbids": recording_mbid,
            "algorithm": self.similar_recordings_algorithm,
        }
        cache_key = (url, tuple(sorted(params.items())))
        with self._lock:
            if cache_key in self._cache:
                payload = copy.deepcopy(self._cache[cache_key])
            else:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                response_recordings = data if isinstance(data, list) else []
                payload = {"recordings": response_recordings}
                self._cache[cache_key] = payload
            cached_recordings = payload.get("recordings")
            if isinstance(cached_recordings, list):
                return {"recordings": copy.deepcopy(cached_recordings[:limit])}
            return {"recordings": []}

    def recording_search(self, artist: str, title: str, limit: int = 10) -> JsonObject:
        url = f"{self.labs_base_url}/recording-search/json"
        params = {"query": f"{artist} {title}"}
        cache_key = (url, tuple(sorted(params.items())))
        with self._lock:
            if cache_key in self._cache:
                payload = copy.deepcopy(self._cache[cache_key])
            else:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                response_recordings = data if isinstance(data, list) else []
                payload = {"recordings": response_recordings}
                self._cache[cache_key] = payload
            cached_recordings = payload.get("recordings")
            if isinstance(cached_recordings, list):
                return {"recordings": copy.deepcopy(cached_recordings[:limit])}
            return {"recordings": []}

    def metadata_lookup(self, artist: str, title: str) -> JsonObject:
        return self._get(
            f"{self.base_url}/metadata/lookup/",
            {"artist_name": artist, "recording_name": title},
        )

    def sitewide_recordings(self, count: int = 100, offset: int = 0) -> JsonObject:
        return self._get(
            f"{self.base_url}/stats/sitewide/recordings",
            {"range": "week", "count": count, "offset": offset},
        )

    def fresh_releases(self, days: int = 7) -> JsonObject:
        return self._get(f"{self.base_url}/explore/fresh-releases/", {"days": days})


class AcousticBrainzClient:
    def __init__(
        self,
        base_url: str = "https://acousticbrainz.org/api/v1",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache: dict[tuple[str, tuple[tuple[str, str | int | float], ...]], JsonObject] = {}
        self._lock = threading.RLock()
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def _get(self, path: str, params: Mapping[str, str | int | float] | None = None) -> JsonObject:
        request_params = params or {}
        cache_key = (path, tuple(sorted(request_params.items())))
        with self._lock:
            if cache_key in self._cache:
                return copy.deepcopy(self._cache[cache_key])
            response = self._client.get(path, params=request_params)
            if response.status_code == 404:
                raise FileNotFoundError(path)
            response.raise_for_status()
            data = response.json()
            result = data if isinstance(data, dict) else {}
            self._cache[cache_key] = result
            return copy.deepcopy(result)

    def count(self, recording_mbid: str) -> int:
        data = self._get(f"/{recording_mbid}/count")
        count = data.get("count")
        return int(count) if isinstance(count, int | float) else 0

    def low_level(self, recording_mbid: str) -> JsonObject:
        return self._get(
            f"/{recording_mbid}/low-level",
            {"features": "rhythm.bpm,tonal.key_key,tonal.key_scale,tonal.key_strength"},
        )

    def high_level(self, recording_mbid: str) -> JsonObject:
        return self._get(
            f"/{recording_mbid}/high-level",
            {
                "features": "genre_dortmund.value,genre_electronic.value,genre_rosamerica.value,genre_tzanetakis.value"
            },
        )
