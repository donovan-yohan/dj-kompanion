from __future__ import annotations

from pathlib import Path

from server.analysis_store import save_analysis
from server.models import (
    AnalysisResult,
    CompatibilityStatus,
    RecommendationSource,
    RecommendedDownloadFilters,
    RecommendedDownloadsRequest,
    SegmentInfo,
)
from server.recommendations.providers import ProviderCandidate, ProviderResult
from server.recommendations.service import RecommendationService
from server.track_db import init_db, mark_analyzed, upsert_track


class StaticProvider:
    def __init__(self, source: RecommendationSource, result: ProviderResult | Exception) -> None:
        self.source = source
        self.result = result
        self.seeds: list[object] = []

    def fetch(self, seed, filters, limit):  # type: ignore[no-untyped-def]
        self.seeds.append(seed)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _analysis(bpm: float = 128, key: str = "A minor", key_camelot: str = "8A") -> AnalysisResult:
    return AnalysisResult(
        bpm=bpm,
        key=key,
        key_camelot=key_camelot,
        beats=[],
        downbeats=[],
        segments=[SegmentInfo(label="intro", original_label="intro", start=0, end=8, bars=4)],
    )


def _analyzed_track(tmp_path: Path, filepath: str = "/music/Seed Artist - Seed Title.m4a") -> tuple[Path, Path]:
    db_path = tmp_path / "tracks.db"
    analysis_dir = tmp_path / "analysis"
    init_db(db_path)
    upsert_track(db_path, filepath)
    analysis_path = save_analysis(analysis_dir, Path(filepath), _analysis())
    mark_analyzed(db_path, filepath, str(analysis_path))
    return db_path, analysis_dir


def test_partial_provider_failure_returns_results(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[
            StaticProvider(
                RecommendationSource.musicbrainz,
                ProviderResult(
                    candidates=[
                        ProviderCandidate(
                            artist="Candidate Artist",
                            title="Candidate Title",
                            recording_mbid="mbid-1",
                            source=RecommendationSource.musicbrainz,
                            source_confidence=0.9,
                            metadata_similarity=0.8,
                        )
                    ],
                    errors=[],
                ),
            ),
            StaticProvider(RecommendationSource.listenbrainz, TimeoutError("listenbrainz timeout")),
        ],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(seed_filepath="/music/Seed Artist - Seed Title.m4a")
    )

    assert len(response.recommendations) == 1
    assert response.recommendations[0].candidate_id == "mbid:mbid-1"
    assert response.provider_errors[0].source == RecommendationSource.listenbrainz
    assert response.provider_errors[0].retryable is True


def test_all_provider_failures_returns_empty_with_errors(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[StaticProvider(RecommendationSource.musicbrainz, TimeoutError("boom"))],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(seed_filepath="/music/Seed Artist - Seed Title.m4a")
    )

    assert response.recommendations == []
    assert response.provider_errors[0].source == RecommendationSource.musicbrainz
    assert "all_provider_failures" in response.warnings


def test_musicbrainz_identity_enriches_seed_for_downstream_providers(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    musicbrainz = StaticProvider(
        RecommendationSource.musicbrainz,
        ProviderResult(
            candidates=[
                ProviderCandidate(
                    artist="Seed Artist",
                    title="Seed Title",
                    recording_mbid="seed-recording-mbid",
                    source=RecommendationSource.musicbrainz,
                    source_confidence=0.9,
                    metadata_similarity=0.95,
                )
            ],
            errors=[],
        ),
    )
    listenbrainz = StaticProvider(
        RecommendationSource.listenbrainz,
        ProviderResult(
            candidates=[
                ProviderCandidate(
                    artist="Recommended Artist",
                    title="Recommended Title",
                    recording_mbid="recommended-mbid",
                    source=RecommendationSource.listenbrainz,
                    source_confidence=0.7,
                    metadata_similarity=0.6,
                )
            ],
            errors=[],
        ),
    )
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[musicbrainz, listenbrainz],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(seed_filepath="/music/Seed Artist - Seed Title.m4a")
    )

    assert listenbrainz.seeds[0].recording_mbid == "seed-recording-mbid"
    assert [rec.title for rec in response.recommendations] == ["Recommended Title"]


def test_dedupe_by_mbid_then_normalized_text(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[
            StaticProvider(
                RecommendationSource.musicbrainz,
                ProviderResult(
                    candidates=[
                        ProviderCandidate(
                            artist="The Candidate",
                            title="A Song",
                            recording_mbid="same-mbid",
                            source=RecommendationSource.musicbrainz,
                            genres=["house"],
                        ),
                        ProviderCandidate(
                            artist="Candidate",
                            title="Song",
                            recording_mbid="same-mbid",
                            source=RecommendationSource.listenbrainz,
                            tags=["dance"],
                        ),
                        ProviderCandidate(
                            artist="The Candidate!!!",
                            title="A Song",
                            source=RecommendationSource.acousticbrainz,
                            tags=["electronic"],
                        ),
                    ],
                    errors=[],
                ),
            )
        ],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(seed_filepath="/music/Seed Artist - Seed Title.m4a")
    )

    assert len(response.recommendations) == 2
    by_id = {rec.candidate_id: rec for rec in response.recommendations}
    assert by_id["mbid:same-mbid"].provider_signals.sources == [
        RecommendationSource.musicbrainz,
        RecommendationSource.listenbrainz,
    ]


def test_exclude_existing_default_and_false_penalizes(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    upsert_track(db_path, "/music/Candidate Artist - Candidate Title.m4a")
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[
            StaticProvider(
                RecommendationSource.musicbrainz,
                ProviderResult(
                    candidates=[
                        ProviderCandidate(
                            artist="Candidate Artist",
                            title="Candidate Title",
                            source=RecommendationSource.musicbrainz,
                            source_confidence=1,
                            metadata_similarity=1,
                        )
                    ],
                    errors=[],
                ),
            )
        ],
    )

    excluded = service.recommend(
        RecommendedDownloadsRequest(seed_filepath="/music/Seed Artist - Seed Title.m4a")
    )
    included = service.recommend(
        RecommendedDownloadsRequest(
            seed_filepath="/music/Seed Artist - Seed Title.m4a",
            filters=RecommendedDownloadFilters(exclude_existing=False),
        )
    )

    assert excluded.recommendations == []
    assert len(included.recommendations) == 1
    assert included.recommendations[0].score_breakdown.dedupe_penalty == 1


def test_service_does_not_load_entire_track_table_for_existing_checks(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    db_path, analysis_dir = _analyzed_track(tmp_path)
    upsert_track(db_path, "/music/Candidate Artist - Candidate Title.m4a")

    def fail_get_all_tracks(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("recommendation service should not scan the full track table")

    monkeypatch.setattr("server.recommendations.service.get_all_tracks", fail_get_all_tracks, raising=False)
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[
            StaticProvider(
                RecommendationSource.musicbrainz,
                ProviderResult(
                    candidates=[
                        ProviderCandidate(
                            artist="Candidate Artist",
                            title="Candidate Title",
                            source=RecommendationSource.musicbrainz,
                        )
                    ],
                    errors=[],
                ),
            )
        ],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(
            seed_filepath="/music/Seed Artist - Seed Title.m4a",
            filters=RecommendedDownloadFilters(exclude_existing=False),
        )
    )

    assert len(response.recommendations) == 1
    assert response.recommendations[0].compatibility.status == CompatibilityStatus.local_analysis_missing


def test_provider_bpm_key_do_not_claim_final_compatibility(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[
            StaticProvider(
                RecommendationSource.musicbrainz,
                ProviderResult(
                    candidates=[
                        ProviderCandidate(
                            artist="Remote Artist",
                            title="Remote Title",
                            bpm=128,
                            key_camelot="8A",
                            source=RecommendationSource.musicbrainz,
                        )
                    ],
                    errors=[],
                ),
            )
        ],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(seed_filepath="/music/Seed Artist - Seed Title.m4a")
    )

    compatibility = response.recommendations[0].compatibility
    assert compatibility.status == "candidate_unvalidated"
    assert compatibility.predicted.bpm_delta == 0
    assert compatibility.final.compatible is None


def test_local_analysis_validated_match_and_mismatch(tmp_path: Path) -> None:
    db_path, analysis_dir = _analyzed_track(tmp_path)
    upsert_track(db_path, "/music/Match Artist - Match Title.m4a")
    match_path = save_analysis(analysis_dir, Path("/music/Match Artist - Match Title.m4a"), _analysis(bpm=130, key_camelot="9A"))
    mark_analyzed(db_path, "/music/Match Artist - Match Title.m4a", str(match_path))
    upsert_track(db_path, "/music/Mismatch Artist - Mismatch Title.m4a")
    mismatch_path = save_analysis(analysis_dir, Path("/music/Mismatch Artist - Mismatch Title.m4a"), _analysis(bpm=150, key_camelot="3A"))
    mark_analyzed(db_path, "/music/Mismatch Artist - Mismatch Title.m4a", str(mismatch_path))
    service = RecommendationService(
        db_path=db_path,
        analysis_dir=analysis_dir,
        providers=[
            StaticProvider(
                RecommendationSource.musicbrainz,
                ProviderResult(
                    candidates=[
                        ProviderCandidate(artist="Match Artist", title="Match Title", source=RecommendationSource.musicbrainz),
                        ProviderCandidate(artist="Mismatch Artist", title="Mismatch Title", source=RecommendationSource.musicbrainz),
                    ],
                    errors=[],
                ),
            )
        ],
    )

    response = service.recommend(
        RecommendedDownloadsRequest(
            seed_filepath="/music/Seed Artist - Seed Title.m4a",
            filters=RecommendedDownloadFilters(exclude_existing=False),
        )
    )

    statuses = {rec.title: rec.compatibility.status for rec in response.recommendations}
    assert statuses["Match Title"] == "locally_validated_match"
    assert statuses["Mismatch Title"] == "locally_validated_mismatch"
