"""Tests for server/edm_reclassify.py — EDM label reclassification."""

from __future__ import annotations

from server.edm_reclassify import RawSegment, reclassify_labels


class TestReclassifyLabels:
    def test_intro_stays_intro(self) -> None:
        segments = [RawSegment(label="intro", start=0.0, end=30.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Intro"

    def test_outro_stays_outro(self) -> None:
        segments = [RawSegment(label="outro", start=300.0, end=330.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Outro"

    def test_verse_stays_verse(self) -> None:
        segments = [RawSegment(label="verse", start=30.0, end=60.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Verse"

    def test_bridge_stays_bridge(self) -> None:
        segments = [RawSegment(label="bridge", start=60.0, end=90.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Bridge"

    def test_inst_becomes_instrumental(self) -> None:
        segments = [RawSegment(label="inst", start=0.0, end=30.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Instrumental"

    def test_solo_becomes_solo(self) -> None:
        segments = [RawSegment(label="solo", start=0.0, end=30.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Solo"

    def test_start_and_end_filtered_out(self) -> None:
        segments = [
            RawSegment(label="start", start=0.0, end=0.1),
            RawSegment(label="intro", start=0.1, end=30.0),
            RawSegment(label="end", start=330.0, end=330.1),
        ]
        result = reclassify_labels(segments, stem_energies=None)
        assert len(result) == 1
        assert result[0].label == "Intro"

    def test_chorus_becomes_drop_with_high_energy(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        # High drums + high bass = Drop
        energies = {(60.0, 90.0): {"drums": 0.8, "bass": 0.7}}
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Drop"

    def test_chorus_stays_chorus_with_low_energy(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        # Low drums + low bass = just Chorus
        energies = {(60.0, 90.0): {"drums": 0.2, "bass": 0.3}}
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Chorus"

    def test_break_before_drop_becomes_buildup(self) -> None:
        segments = [
            RawSegment(label="break", start=50.0, end=60.0),
            RawSegment(label="chorus", start=60.0, end=90.0),
        ]
        energies = {
            (50.0, 60.0): {"drums": 0.3, "bass": 0.2},
            (60.0, 90.0): {"drums": 0.8, "bass": 0.7},
        }
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Buildup"
        assert result[1].label == "Drop"

    def test_break_not_before_drop_becomes_breakdown(self) -> None:
        segments = [
            RawSegment(label="break", start=90.0, end=120.0),
            RawSegment(label="verse", start=120.0, end=150.0),
        ]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Breakdown"

    def test_chorus_without_energy_data_stays_chorus(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        result = reclassify_labels(segments, stem_energies=None)
        assert result[0].label == "Chorus"

    def test_preserves_original_label(self) -> None:
        segments = [RawSegment(label="chorus", start=60.0, end=90.0)]
        energies = {(60.0, 90.0): {"drums": 0.8, "bass": 0.7}}
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].original_label == "chorus"

    def test_numbered_labels_for_repeated_sections(self) -> None:
        segments = [
            RawSegment(label="chorus", start=60.0, end=90.0),
            RawSegment(label="break", start=90.0, end=105.0),
            RawSegment(label="chorus", start=105.0, end=135.0),
        ]
        energies = {
            (60.0, 90.0): {"drums": 0.8, "bass": 0.7},
            (90.0, 105.0): {"drums": 0.2, "bass": 0.2},
            (105.0, 135.0): {"drums": 0.8, "bass": 0.7},
        }
        result = reclassify_labels(segments, stem_energies=energies)
        assert result[0].label == "Drop 1"
        assert result[2].label == "Drop 2"
