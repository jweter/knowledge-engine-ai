from __future__ import annotations

import pytest

from knowledge_engine_ai.general_query_plan import EvidenceScope, QueryFrameType
from knowledge_engine_ai.research_case_benchmark import GoldenResearchCase
from knowledge_engine_ai.research_case_query_plan import monster_energy_bp_query_plan


def test_monster_query_plan_covers_every_benchmark_search_track() -> None:
    plan = monster_energy_bp_query_plan()

    track_ids = {track.track_id for track in plan.tracks}
    assert {
        "direct_monster_or_commercial_energy_drink_trials",
        "energy_drink_randomized_or_meta_analysis",
        "repeated_or_chronic_energy_drink_exposure",
        "chronic_caffeine_randomized_or_meta_analysis",
        "sugar_sweetened_beverage_incident_hypertension",
        "artificially_sweetened_beverage_context",
        "clinical_bp_measurement_guidance",
        "direct_6_12_month_or_one_year_energy_drink_longitudinal",
    } <= track_ids
    assert "counterevidence_or_null_findings" in track_ids


def test_monster_query_plan_preserves_direct_class_indirect_guidance_and_counter_scopes() -> None:
    plan = monster_energy_bp_query_plan()

    scopes = {track.scope for track in plan.tracks}
    assert scopes == {
        EvidenceScope.DIRECT,
        EvidenceScope.CLASS_LEVEL,
        EvidenceScope.INDIRECT_CONTEXT,
        EvidenceScope.GUIDANCE,
        EvidenceScope.COUNTEREVIDENCE,
    }


def test_monster_query_plan_preserves_benchmark_dimensions_and_seed_pmids() -> None:
    plan = monster_energy_bp_query_plan()

    assert {
        "acute_pressor_effect",
        "persistent_chronic_bp_effect",
        "incident_hypertension_risk",
        "measurement_artifact",
        "direct_vs_class_level_evidence",
        "certainty_and_missing_evidence",
    } <= set(plan.answer_dimensions)
    assert {
        "pmid:37695306",
        "pmid:26931509",
        "pmid:26708636",
        "pmid:38057002",
    } <= set(plan.seed_source_ids)


def test_monster_query_plan_is_generic_frame_not_forced_into_single_pico() -> None:
    plan = monster_energy_bp_query_plan()

    assert plan.frame_type is QueryFrameType.GENERIC
    assert plan.pico is None
    assert plan.domain_hint == "cardiovascular_nutrition"


def test_monster_query_plan_has_explicit_long_term_and_counterevidence_queries() -> None:
    plan = monster_energy_bp_query_plan()

    long_term_queries = [
        variant.query
        for variant in plan.query_variants
        if variant.track_id == "direct_6_12_month_or_one_year_energy_drink_longitudinal"
    ]
    counter_queries = [
        variant.query
        for variant in plan.query_variants
        if variant.track_id == "counterevidence_or_null_findings"
    ]

    assert long_term_queries
    assert any("12 months" in query or "one year" in query for query in long_term_queries)
    assert counter_queries
    assert any(
        phrase in query
        for query in counter_queries
        for phrase in ("no significant change", "null finding", "tolerance", "not significant")
    )


def test_monster_query_plan_budget_keeps_at_least_one_query_per_track() -> None:
    plan = monster_energy_bp_query_plan(max_total_variants=9)

    assert len(plan.query_variants) == 9
    assert {variant.track_id for variant in plan.query_variants} == {
        track.track_id for track in plan.tracks
    }


def test_monster_query_plan_rejects_budget_smaller_than_track_count() -> None:
    with pytest.raises(ValueError, match="at least the number of search tracks"):
        monster_energy_bp_query_plan(max_total_variants=8)


def test_monster_fixture_rejects_unrelated_golden_case() -> None:
    unrelated = GoldenResearchCase(
        case_id="other-case",
        domain="biology",
        question="Does X affect Y?",
        required_variants=("x",),
        required_dimensions=("effect",),
        required_search_tracks=("track",),
        required_seed_source_ids=("pmid:1",),
        required_source_fields=("population",),
    )

    with pytest.raises(ValueError, match="requires case"):
        monster_energy_bp_query_plan(unrelated)
