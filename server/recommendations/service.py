from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from server.analysis_store import load_analysis
from server.models import (
    CompatibilityStatus,
    ProviderError,
    ProviderSignals,
    RecommendationActions,
    RecommendationCompatibility,
    RecommendationCompatibilityFinal,
    RecommendationCompatibilityPredicted,
    RecommendationSeed,
    RecommendationSource,
    RecommendedDownload,
    RecommendedDownloadsRequest,
    RecommendedDownloadsResponse,
)
from server.recommendations.providers import (
    ProviderCandidate,
    ProviderResult,
    ProviderSeed,
    RecommendationProvider,
)
from server.recommendations.scoring import (
    _text_key,
    camelot_relation,
    normalize_artist_title,
    score_candidate,
    stable_candidate_id,
)
from server.track_db import TrackRow, get_track, get_tracks_matching_terms


class SeedNotFoundError(Exception):
    def __init__(self, filepath: Path) -> None:
        super().__init__(f"Seed track not found: {filepath}")
        self.filepath = filepath


class SeedAnalysisRequiredError(Exception):
    def __init__(self, filepath: Path) -> None:
        super().__init__(f"Seed track requires local analysis: {filepath}")
        self.filepath = filepath


class RecommendationService:
    def __init__(
        self,
        db_path: Path,
        analysis_dir: Path,
        providers: list[RecommendationProvider],
    ) -> None:
        self.db_path = db_path
        self.analysis_dir = analysis_dir
        self.providers = providers

    def recommend(self, request: RecommendedDownloadsRequest) -> RecommendedDownloadsResponse:
        seed_filepath = request.seed_filepath or (request.seed_filepaths or [""])[0]
        seed_track = get_track(self.db_path, seed_filepath)
        if seed_track is None:
            raise SeedNotFoundError(Path(seed_filepath))
        seed_analysis = load_analysis(Path(seed_track.analysis_path)) if seed_track.analysis_path else None
        if seed_analysis is None:
            raise SeedAnalysisRequiredError(Path(seed_filepath))

        warnings: list[str] = []
        seed_artist, seed_title = _artist_title_from_path(seed_filepath)
        if seed_artist == "Unknown Artist":
            warnings.append("seed_metadata_limited")
        seed = ProviderSeed(
            filepath=seed_filepath,
            artist=seed_artist,
            title=seed_title,
            bpm=seed_analysis.bpm,
            key=seed_analysis.key,
            key_camelot=seed_analysis.key_camelot,
        )

        provider_errors: list[ProviderError] = []
        candidates: list[ProviderCandidate] = []
        sources_used: list[RecommendationSource] = []
        requested_sources = set(request.sources)
        for provider in self.providers:
            if provider.source not in requested_sources:
                continue
            try:
                result = provider.fetch(seed, request.filters, request.limit)
            except Exception as exc:
                result = ProviderResult(
                    candidates=[],
                    errors=[ProviderError(source=provider.source, error=str(exc), retryable=True)],
                )
            provider_errors.extend(result.errors)
            if seed.recording_mbid is None and provider.source == RecommendationSource.musicbrainz:
                seed_mbid = _seed_identity_mbid(seed, result.candidates)
                if seed_mbid:
                    seed = replace(seed, recording_mbid=seed_mbid)
            if result.candidates:
                sources_used.append(provider.source)
                candidates.extend(result.candidates)

        if not candidates and provider_errors:
            warnings.append("all_provider_failures")

        merged_candidates = _merge_candidates(candidates)
        local_tracks = get_tracks_matching_terms(self.db_path, _candidate_search_terms(merged_candidates))
        existing = _existing_index(local_tracks)
        recommendations: list[RecommendedDownload] = []
        for candidate in merged_candidates:
            candidate_id = stable_candidate_id(candidate)
            candidate_text_key = _text_key(candidate.artist, candidate.title)
            local_track = existing.get(candidate_id) or existing.get(candidate_text_key)
            already_exists = local_track is not None
            if already_exists and request.filters.exclude_existing:
                continue

            score, breakdown = score_candidate(candidate, seed, request.filters, already_exists)
            recommendations.append(
                RecommendedDownload(
                    candidate_id=candidate_id,
                    artist=candidate.artist,
                    title=candidate.title,
                    recording_mbid=candidate.recording_mbid,
                    release_mbid=candidate.release_mbid,
                    source_urls=candidate.source_urls,
                    provider_signals=ProviderSignals(
                        sources=_candidate_sources(candidate),
                        genres=candidate.genres,
                        tags=candidate.tags,
                        bpm=candidate.bpm,
                        key=candidate.key,
                        key_camelot=candidate.key_camelot,
                    ),
                    score=score,
                    score_breakdown=breakdown,
                    compatibility=_compatibility(seed, candidate, local_track, request.filters.bpm_tolerance),
                    actions=RecommendationActions(
                        search_query=f"{candidate.artist} {candidate.title}",
                        musicbrainz_url=candidate.source_urls.get("musicbrainz"),
                    ),
                )
            )

        recommendations.sort(
            key=lambda rec: (
                -rec.score,
                -rec.score_breakdown.source_confidence,
                normalize_artist_title(rec.artist),
                normalize_artist_title(rec.title),
                rec.candidate_id,
            )
        )
        return RecommendedDownloadsResponse(
            seed=RecommendationSeed(
                filepath=seed_filepath,
                bpm=seed_analysis.bpm,
                key=seed_analysis.key,
                key_camelot=seed_analysis.key_camelot,
                status="analyzed",
            ),
            recommendations=recommendations[: request.limit],
            sources_used=sources_used,
            provider_errors=provider_errors,
            warnings=warnings,
        )


def _artist_title_from_path(filepath: str) -> tuple[str, str]:
    stem = Path(filepath).stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip() or "Unknown Artist", title.strip() or stem
    return "Unknown Artist", stem


def _seed_identity_mbid(seed: ProviderSeed, candidates: list[ProviderCandidate]) -> str | None:
    seed_key = _text_key(seed.artist, seed.title)
    for candidate in candidates:
        if candidate.recording_mbid and _text_key(candidate.artist, candidate.title) == seed_key:
            return candidate.recording_mbid
    for candidate in candidates:
        if candidate.recording_mbid:
            return candidate.recording_mbid
    return None


def _merge_candidates(candidates: list[ProviderCandidate]) -> list[ProviderCandidate]:
    merged: dict[str, ProviderCandidate] = {}
    order: list[str] = []
    for candidate in candidates:
        key = f"mbid:{candidate.recording_mbid}" if candidate.recording_mbid else _text_key(candidate.artist, candidate.title)
        if key not in merged:
            merged[key] = candidate
            order.append(key)
            continue
        existing = merged[key]
        combined_source_urls = {**existing.source_urls, **candidate.source_urls}
        merged[key] = replace(
            existing,
            source=existing.source,
            sources=_dedupe_sources(_candidate_sources(existing) + _candidate_sources(candidate)),
            release_mbid=existing.release_mbid or candidate.release_mbid,
            source_urls=combined_source_urls,
            genres=_dedupe(existing.genres + candidate.genres),
            tags=_dedupe(existing.tags + candidate.tags),
            bpm=existing.bpm if existing.bpm is not None else candidate.bpm,
            key=existing.key if existing.key is not None else candidate.key,
            key_camelot=existing.key_camelot if existing.key_camelot is not None else candidate.key_camelot,
            source_confidence=max(existing.source_confidence, candidate.source_confidence),
            metadata_similarity=max(existing.metadata_similarity, candidate.metadata_similarity),
        )
    return [merged[key] for key in order]


def _candidate_sources(candidate: ProviderCandidate) -> list[RecommendationSource]:
    return _dedupe_sources(candidate.sources or [candidate.source])


def _dedupe_sources(values: list[RecommendationSource]) -> list[RecommendationSource]:
    seen: set[RecommendationSource] = set()
    deduped: list[RecommendationSource] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = normalize_artist_title(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def _existing_index(tracks: list[TrackRow]) -> dict[str, TrackRow]:
    index: dict[str, TrackRow] = {}
    for track in tracks:
        artist, title = _artist_title_from_path(track.filepath)
        index[_text_key(artist, title)] = track
    return index


def _candidate_search_terms(candidates: list[ProviderCandidate]) -> list[str]:
    terms: list[str] = []
    for candidate in candidates:
        terms.extend([candidate.artist, candidate.title])
    return _dedupe([normalize_artist_title(term) for term in terms if term])


def _compatibility(
    seed: ProviderSeed,
    candidate: ProviderCandidate,
    local_track: TrackRow | None,
    bpm_tolerance: float,
) -> RecommendationCompatibility:
    predicted_delta = None
    if seed.bpm is not None and candidate.bpm is not None:
        predicted_delta = abs(seed.bpm - candidate.bpm)
    predicted_relation = camelot_relation(seed.key_camelot, candidate.key_camelot)
    predicted = RecommendationCompatibilityPredicted(
        bpm_delta=predicted_delta,
        camelot_relation=predicted_relation,
    )
    final = RecommendationCompatibilityFinal()
    if local_track is None:
        return RecommendationCompatibility(
            status=CompatibilityStatus.candidate_unvalidated,
            reason="remote candidate has not been downloaded/analyzed locally",
            predicted=predicted,
            final=final,
        )
    local_analysis = load_analysis(Path(local_track.analysis_path)) if local_track.analysis_path else None
    if local_analysis is None:
        return RecommendationCompatibility(
            status=CompatibilityStatus.local_analysis_missing,
            reason="matching local track exists but local analysis is missing",
            predicted=predicted,
            final=final,
        )
    bpm_delta = abs(seed.bpm - local_analysis.bpm) if seed.bpm is not None else None
    relation = camelot_relation(seed.key_camelot, local_analysis.key_camelot)
    compatible = (bpm_delta is None or bpm_delta <= bpm_tolerance) and relation in {
        "same",
        "adjacent",
        "energy_safe",
        "unknown",
    }
    return RecommendationCompatibility(
        status=CompatibilityStatus.locally_validated_match
        if compatible
        else CompatibilityStatus.locally_validated_mismatch,
        reason="matched local track validated with analyzer sidecar",
        predicted=predicted,
        final=RecommendationCompatibilityFinal(
            bpm=local_analysis.bpm,
            key_camelot=local_analysis.key_camelot,
            compatible=compatible,
        ),
    )
