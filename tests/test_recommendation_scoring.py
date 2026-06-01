from __future__ import annotations

from server.models import CamelotPolicy, RecommendationSource, RecommendedDownloadFilters
from server.recommendations.providers import ProviderCandidate, ProviderSeed
from server.recommendations.scoring import (
    camelot_relation,
    score_candidate,
    sort_candidates,
    stable_candidate_id,
)


def test_stable_candidate_id_prefers_mbid() -> None:
    candidate = ProviderCandidate(
        artist="Artist",
        title="Title",
        recording_mbid="abc-123",
        source=RecommendationSource.musicbrainz,
    )

    assert stable_candidate_id(candidate) == "mbid:abc-123"


def test_stable_candidate_id_falls_back_to_normalized_text_hash() -> None:
    candidate = ProviderCandidate(
        artist="The Artist!!!",
        title="  A Title  ",
        source=RecommendationSource.musicbrainz,
    )

    assert stable_candidate_id(candidate).startswith("text:")
    assert stable_candidate_id(candidate) == stable_candidate_id(
        ProviderCandidate(
            artist="artist",
            title="title",
            source=RecommendationSource.listenbrainz,
        )
    )


def test_camelot_relation_classifies_same_adjacent_and_energy_safe() -> None:
    assert camelot_relation("8A", "8A") == "same"
    assert camelot_relation("8A", "9A") == "adjacent"
    assert camelot_relation("8A", "7A") == "adjacent"
    assert camelot_relation("12B", "1B") == "adjacent"
    assert camelot_relation("8A", "9B") == "energy_safe"
    assert camelot_relation("8A", "3A") == "incompatible"
    assert camelot_relation(None, "3A") == "unknown"


def test_score_candidate_uses_low_confidence_bpm_and_key_hints() -> None:
    seed = ProviderSeed(filepath="/music/seed.m4a", artist="Seed", title="Track", bpm=128, key_camelot="8A", genres=["house"])
    candidate = ProviderCandidate(
        artist="Candidate",
        title="Track",
        genres=["house", "dance"],
        bpm=130,
        key_camelot="9A",
        source=RecommendationSource.listenbrainz,
        source_confidence=0.8,
        metadata_similarity=0.7,
    )

    score, breakdown = score_candidate(candidate, seed, RecommendedDownloadFilters())

    assert breakdown.bpm_hint == 0.25
    assert breakdown.camelot_hint == 0.4
    assert breakdown.genre_tag_overlap > 0
    assert breakdown.dedupe_penalty == 0
    assert score == round(score, 4)
    assert 0 < score < 1


def test_score_candidate_applies_dedupe_penalty() -> None:
    seed = ProviderSeed(filepath="/music/seed.m4a", artist="Seed", title="Track", bpm=128, key_camelot="8A")
    candidate = ProviderCandidate(
        artist="Candidate",
        title="Track",
        bpm=128,
        key_camelot="8A",
        source=RecommendationSource.musicbrainz,
        source_confidence=1,
        metadata_similarity=1,
    )

    normal_score, _ = score_candidate(candidate, seed, RecommendedDownloadFilters(), already_exists=False)
    dedupe_score, breakdown = score_candidate(candidate, seed, RecommendedDownloadFilters(), already_exists=True)

    assert breakdown.dedupe_penalty == 1
    assert dedupe_score < normal_score


def test_sort_candidates_is_deterministic() -> None:
    seed = ProviderSeed(filepath="/music/seed.m4a", artist="Seed", title="Track", bpm=128, key_camelot="8A")
    filters = RecommendedDownloadFilters(camelot_policy=CamelotPolicy.adjacent)
    candidates = [
        ProviderCandidate(artist="Zed", title="B", source=RecommendationSource.musicbrainz, source_confidence=0.5, metadata_similarity=0.5),
        ProviderCandidate(artist="Alpha", title="B", source=RecommendationSource.musicbrainz, source_confidence=0.5, metadata_similarity=0.5),
        ProviderCandidate(artist="Alpha", title="A", source=RecommendationSource.musicbrainz, source_confidence=0.5, metadata_similarity=0.5),
    ]

    ordered = sort_candidates(candidates, seed, filters)

    assert [(c.artist, c.title) for c, _, _ in ordered] == [("Alpha", "A"), ("Alpha", "B"), ("Zed", "B")]
