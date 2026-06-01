from __future__ import annotations

import hashlib
import re
from string import punctuation
from typing import TYPE_CHECKING

from server.models import CamelotPolicy, RecommendedDownloadFilters, ScoreBreakdown

if TYPE_CHECKING:
    from server.recommendations.providers import ProviderCandidate, ProviderSeed

_ARTICLES = {"a", "an", "the"}
_CAMEL0T_RE = re.compile(r"^(1[0-2]|[1-9])([AB])$", re.IGNORECASE)


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def normalize_artist_title(text: str) -> str:
    cleaned = text.lower().translate(str.maketrans("", "", punctuation))
    words = [word for word in cleaned.split() if word not in _ARTICLES]
    return " ".join(words)


def stable_candidate_id(candidate: ProviderCandidate) -> str:
    if candidate.recording_mbid:
        return f"mbid:{candidate.recording_mbid}"
    normalized = f"{normalize_artist_title(candidate.artist)}\0{normalize_artist_title(candidate.title)}"
    digest = hashlib.sha1(normalized.encode()).hexdigest()[:16]
    return f"text:{digest}"


def _parse_camelot(value: str | None) -> tuple[int, str] | None:
    if value is None:
        return None
    match = _CAMEL0T_RE.match(value.strip())
    if match is None:
        return None
    return int(match.group(1)), match.group(2).upper()


def _distance(a: int, b: int) -> int:
    raw = abs(a - b)
    return min(raw, 12 - raw)


def camelot_relation(seed_key: str | None, candidate_key: str | None) -> str:
    seed = _parse_camelot(seed_key)
    candidate = _parse_camelot(candidate_key)
    if seed is None or candidate is None:
        return "unknown"
    seed_num, seed_mode = seed
    candidate_num, candidate_mode = candidate
    if seed_num == candidate_num and seed_mode == candidate_mode:
        return "same"
    if seed_mode == candidate_mode and _distance(seed_num, candidate_num) == 1:
        return "adjacent"
    if seed_mode != candidate_mode and _distance(seed_num, candidate_num) <= 1:
        return "energy_safe"
    return "incompatible"


def _jaccard(left: list[str], right: list[str]) -> float:
    left_set = {normalize_artist_title(item) for item in left if item}
    right_set = {normalize_artist_title(item) for item in right if item}
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _camelot_allowed(relation: str, policy: CamelotPolicy) -> bool:
    if relation == "unknown":
        return True
    if policy == CamelotPolicy.same:
        return relation == "same"
    if policy == CamelotPolicy.adjacent:
        return relation in {"same", "adjacent"}
    return relation in {"same", "adjacent", "energy_safe"}


def score_candidate(
    candidate: ProviderCandidate,
    seed: ProviderSeed,
    filters: RecommendedDownloadFilters,
    already_exists: bool = False,
) -> tuple[float, ScoreBreakdown]:
    source_confidence = clamp(candidate.source_confidence)
    metadata_similarity = clamp(candidate.metadata_similarity)
    genre_tag_overlap = _jaccard(seed.genres + seed.tags, candidate.genres + candidate.tags)

    bpm_hint = 0.0
    if seed.bpm is not None and candidate.bpm is not None:
        if filters.bpm_tolerance == 0:
            bpm_hint = 0.5 if seed.bpm == candidate.bpm else 0.0
        else:
            bpm_hint = max(0.0, 1 - abs(seed.bpm - candidate.bpm) / filters.bpm_tolerance) * 0.5

    relation = camelot_relation(seed.key_camelot, candidate.key_camelot)
    camelot_hint = {
        "same": 0.5,
        "adjacent": 0.4,
        "energy_safe": 0.3,
    }.get(relation, 0.0)
    if not _camelot_allowed(relation, filters.camelot_policy):
        camelot_hint = 0.0

    dedupe_penalty = 1.0 if already_exists else 0.0
    raw_score = (
        0.30 * source_confidence
        + 0.25 * metadata_similarity
        + 0.20 * genre_tag_overlap
        + 0.15 * bpm_hint
        + 0.10 * camelot_hint
        - 0.50 * dedupe_penalty
    )
    score = round(clamp(raw_score), 4)
    return score, ScoreBreakdown(
        source_confidence=source_confidence,
        metadata_similarity=metadata_similarity,
        genre_tag_overlap=round(genre_tag_overlap, 4),
        bpm_hint=round(bpm_hint, 4),
        camelot_hint=camelot_hint,
        dedupe_penalty=dedupe_penalty,
    )


def sort_candidates(
    candidates: list[ProviderCandidate],
    seed: ProviderSeed,
    filters: RecommendedDownloadFilters,
    existing_keys: set[str] | None = None,
) -> list[tuple[ProviderCandidate, float, ScoreBreakdown]]:
    existing = existing_keys or set()
    scored = [
        (
            candidate,
            *score_candidate(
                candidate,
                seed,
                filters,
                already_exists=stable_candidate_id(candidate) in existing
                or _text_key(candidate.artist, candidate.title) in existing,
            ),
        )
        for candidate in candidates
    ]
    return sorted(
        scored,
        key=lambda item: (
            -item[1],
            -clamp(item[0].source_confidence),
            normalize_artist_title(item[0].artist),
            normalize_artist_title(item[0].title),
            stable_candidate_id(item[0]),
        ),
    )


def _text_key(artist: str, title: str) -> str:
    return f"textkey:{normalize_artist_title(artist)}\0{normalize_artist_title(title)}"
