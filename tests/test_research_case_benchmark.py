from __future__ import annotations

import pytest

from knowledge_engine_ai.research_case_benchmark import (
    GoldenResearchCase,
    ResearchCaseRunSnapshot,
    SourceFieldGap,
    default_golden_research_cases,
    evaluate_research_case,
)


def _monster_case() -> GoldenResearchCase:
    return default_golden_research_cases()[0]


def _complete_snapshot(**overrides: object) -> ResearchCaseRunSnapshot:
    case = _monster_case()
    values: dict[str, object] = {
        "case_id": case.case_id,
        "initial_indexed_evidence_record_count": 0,
        "discovery_triggered": True,
        "attempted_providers": ("pubmed", "openalex", "crossref"),
        "degraded_providers": (),
        "reported_degraded_providers": (),
        "covered_variants": case.required_variants,
        "covered_dimensions": case.required_dimensions,
        "completed_search_tracks": case.required_search_tracks,
        "reviewed_source_ids": case.required_seed_source_ids,
        "represented_counterevidence_source_ids": case.counterevidence_seed_source_ids,
        "source_fields_audited_source_ids": case.required_seed_source_ids,
        "direct_long_term_study_found": False,
        "direct_long_term_gap_reported": True,
        "factual_claim_count": 12,
        "source_linked_factual_claim_count": 12,
        "source_field_gaps": (),
        "violated_inference_guard_ids": (),
    }
    values.update(overrides)
    return ResearchCaseRunSnapshot(**values)  # type: ignore[arg-type]


def test_monster_case_encodes_issue_79_required_separations_and_seeds() -> None:
    case = _monster_case()

    assert case.case_id == "monster-energy-bp-one-year"
    assert case.required_variants == (
        "monster_zero_ultra_two_16oz_per_day",
        "monster_original_two_16oz_per_day",
    )
    assert {
        "acute_pressor_effect",
        "persistent_chronic_bp_effect",
        "incident_hypertension_risk",
        "measurement_artifact",
    } <= set(case.required_dimensions)
    assert "direct_6_12_month_or_one_year_energy_drink_longitudinal" in (
        case.required_search_tracks
    )
    assert "pmid:37695306" in case.required_seed_source_ids
    assert "pmid:26931509" in case.counterevidence_seed_source_ids
    assert "pmid:26708636" in case.counterevidence_seed_source_ids
    assert case.required_providers == ("pubmed",)
    assert case.minimum_attempted_providers >= 2
    assert "direct_vs_class_level_evidence" in case.required_dimensions
    assert "certainty_and_missing_evidence" in case.required_dimensions
    assert {
        "population",
        "dose",
        "duration",
        "bp_measurement_method",
        "effect_size",
        "confidence_interval",
        "risk_of_bias_or_limitations",
    } <= set(case.required_source_fields)
    assert case.require_long_term_gap_disclosure_when_absent is True


def test_complete_monster_research_snapshot_passes() -> None:
    result = evaluate_research_case(_monster_case(), _complete_snapshot())

    assert result.passes is True
    assert result.missing_variants == ()
    assert result.missing_dimensions == ()
    assert result.missing_search_tracks == ()
    assert result.missing_seed_source_ids == ()
    assert result.missing_counterevidence_seed_source_ids == ()
    assert result.unlinked_factual_claim_count == 0


def test_missing_chronic_dimension_and_counterevidence_fail_visibly() -> None:
    case = _monster_case()
    dimensions = tuple(
        dimension
        for dimension in case.required_dimensions
        if dimension != "persistent_chronic_bp_effect"
    )
    counterevidence = tuple(
        source_id
        for source_id in case.counterevidence_seed_source_ids
        if source_id != "pmid:26708636"
    )

    result = evaluate_research_case(
        case,
        _complete_snapshot(
            covered_dimensions=dimensions,
            represented_counterevidence_source_ids=counterevidence,
        ),
    )

    assert result.passes is False
    assert result.missing_dimensions == ("persistent_chronic_bp_effect",)
    assert result.missing_counterevidence_seed_source_ids == ("pmid:26708636",)


def test_empty_index_requires_bounded_discovery() -> None:
    result = evaluate_research_case(
        _monster_case(),
        _complete_snapshot(discovery_triggered=False),
    )

    assert result.discovery_required_but_not_triggered is True
    assert result.passes is False


def test_pubmed_plus_another_scholarly_provider_are_required() -> None:
    case = _monster_case()

    result = evaluate_research_case(
        case,
        _complete_snapshot(attempted_providers=("crossref",)),
    )

    assert result.missing_required_providers == ("pubmed",)
    assert result.provider_count_shortfall == 1
    assert result.passes is False


def test_absent_direct_long_term_study_requires_explicit_gap_disclosure() -> None:
    result = evaluate_research_case(
        _monster_case(),
        _complete_snapshot(
            direct_long_term_study_found=False,
            direct_long_term_gap_reported=False,
        ),
    )

    assert result.long_term_gap_disclosure_missing is True
    assert result.passes is False


def test_found_direct_long_term_study_does_not_require_absence_statement() -> None:
    result = evaluate_research_case(
        _monster_case(),
        _complete_snapshot(
            direct_long_term_study_found=True,
            direct_long_term_gap_reported=False,
        ),
    )

    assert result.long_term_gap_disclosure_missing is False
    assert result.passes is True


def test_unlinked_claims_and_inference_guard_violations_fail() -> None:
    case = _monster_case()
    guard_id = "do_not_claim_one_year_monster_trial_without_direct_source"

    result = evaluate_research_case(
        case,
        _complete_snapshot(
            factual_claim_count=10,
            source_linked_factual_claim_count=8,
            violated_inference_guard_ids=(guard_id,),
        ),
    )

    assert result.unlinked_factual_claim_count == 2
    assert result.violated_inference_guard_ids == (guard_id,)
    assert result.passes is False


def test_degraded_provider_must_be_reported_explicitly() -> None:
    result = evaluate_research_case(
        _monster_case(),
        _complete_snapshot(
            degraded_providers=("openalex",),
            reported_degraded_providers=(),
        ),
    )

    assert result.unreported_degraded_providers == ("openalex",)
    assert result.passes is False


def test_each_required_seed_requires_per_source_field_audit() -> None:
    case = _monster_case()
    audited = tuple(
        source_id for source_id in case.required_seed_source_ids if source_id != "pmid:33341807"
    )

    result = evaluate_research_case(
        case,
        _complete_snapshot(source_fields_audited_source_ids=audited),
    )

    assert result.missing_source_field_audits == ("pmid:33341807",)
    assert result.passes is False


def test_missing_required_source_field_fails_visibly() -> None:
    result = evaluate_research_case(
        _monster_case(),
        _complete_snapshot(
            source_field_gaps=(
                SourceFieldGap(
                    source_id="pmid:37695306",
                    missing_fields=("confidence_interval",),
                ),
            ),
        ),
    )

    assert result.source_field_gaps[0].source_id == "pmid:37695306"
    assert result.source_field_gaps[0].missing_fields == ("confidence_interval",)
    assert result.passes is False


def test_snapshot_rejects_degraded_provider_that_was_not_attempted() -> None:
    with pytest.raises(ValueError, match="subset of attempted_providers"):
        _complete_snapshot(degraded_providers=("semantic_scholar",))


def test_case_rejects_counterevidence_seed_outside_required_seed_bank() -> None:
    with pytest.raises(ValueError, match="must also be required"):
        GoldenResearchCase(
            case_id="case",
            domain="test",
            question="Question?",
            required_variants=("variant",),
            required_dimensions=("dimension",),
            required_search_tracks=("track",),
            required_seed_source_ids=("pmid:1",),
            required_source_fields=("population",),
            counterevidence_seed_source_ids=("pmid:2",),
        )


def test_snapshot_case_id_must_match_case() -> None:
    with pytest.raises(ValueError, match="does not match"):
        evaluate_research_case(
            _monster_case(),
            _complete_snapshot(case_id="different-case"),
        )
