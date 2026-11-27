from __future__ import annotations

import json

from knowledge_engine_ai.orchestrator.funnel_conversion import (
    FunnelConversion,
    compute_funnel_conversion,
)
from knowledge_engine_ai.orchestrator.funnel_report import (
    AcquisitionFunnel,
    AcquisitionPlanFunnel,
    ExtractionFunnel,
    ResearchConversionFunnelReport,
)


def _plan(resolved: int = 10, indexed: int = 2, eligible: int = 6) -> AcquisitionPlanFunnel:
    return AcquisitionPlanFunnel(
        resolved_candidate_count=resolved,
        already_indexed_count=indexed,
        full_text_eligible_count=eligible,
        metadata_only_count=0,
        skipped_budget_count=0,
        missing_candidate_count=0,
    )


def _acquisition(persisted: int = 5, reused: int = 2) -> AcquisitionFunnel:
    return AcquisitionFunnel(
        routes_attempted=7,
        routes_skipped=0,
        routes_failed=0,
        papers_persisted=persisted,
        papers_reused=reused,
    )


def _extraction(
    draft: int = 40, classified: int = 30, staged: int = 20, grounded: int = 18, promoted: int = 15
) -> ExtractionFunnel:
    return ExtractionFunnel(
        draft_item_count=draft,
        classified_item_count=classified,
        unclassified_draft_count=draft - classified,
        staged_record_count=staged,
        grounded_record_count=grounded,
        promoted_record_count=promoted,
        grounding_failure_count=staged - grounded,
        rejected_after_classification_count=classified - promoted,
    )


def _report(
    *,
    discovery: bool = True,
    federated: int = 12,
    plan: AcquisitionPlanFunnel | None = None,
    acquisition: AcquisitionFunnel | None = None,
    extraction: ExtractionFunnel | None = None,
) -> ResearchConversionFunnelReport:
    return ResearchConversionFunnelReport(
        schema_version=1,
        session_id="s1",
        discovery_triggered=discovery,
        federated_discovery_candidate_count=federated,
        citation_snowball_candidate_count=0,
        acquisition_plan=plan,
        acquisition=acquisition,
        extraction=extraction,
        reretrieval_attempted=False,
        reretrieval_succeeded=False,
        reretrieval_evidence_record_count=0,
        indexed_evidence_record_count=0,
        newly_promoted_evidence_record_count=0,
        time_to_first_grounded_information_ms=None,
        time_to_final_report_ms=None,
    )


def _full() -> ResearchConversionFunnelReport:
    return _report(plan=_plan(), acquisition=_acquisition(), extraction=_extraction())


def test_full_chain_links_every_stage_in_pipeline_order() -> None:
    conversion = compute_funnel_conversion(_full())

    assert [(link.from_stage, link.to_stage) for link in conversion.links] == [
        ("federated_candidates", "plan_resolved"),
        ("plan_resolved", "acquirable"),
        ("acquirable", "papers_obtained"),
        ("papers_obtained", "draft_items"),
        ("draft_items", "classified"),
        ("classified", "staged"),
        ("staged", "grounded"),
        ("grounded", "promoted"),
    ]


def test_rates_and_losses_are_plain_arithmetic() -> None:
    links = {link.to_stage: link for link in compute_funnel_conversion(_full()).links}

    assert (links["plan_resolved"].entered, links["plan_resolved"].converted) == (12, 10)
    assert links["plan_resolved"].rate == 10 / 12
    assert links["acquirable"].converted == 8  # 2 already indexed + 6 eligible
    assert links["acquirable"].lost == 2
    assert links["classified"].rate == 0.75
    assert links["promoted"].lost == 3


def test_largest_drop_off_is_the_link_that_lost_the_most_items() -> None:
    # draft 40 -> classified 30 and classified 30 -> staged 20 both lose 10 (the biggest loss);
    # the tie goes to the earlier link.
    conversion = compute_funnel_conversion(_full())

    assert conversion.largest_drop_off is not None
    assert (conversion.largest_drop_off.from_stage, conversion.largest_drop_off.to_stage) == (
        "draft_items",
        "classified",
    )
    assert conversion.largest_drop_off.lost == 10


def test_inflating_links_are_flagged_and_never_the_largest_drop_off() -> None:
    conversion = compute_funnel_conversion(_full())
    inflating = [link for link in conversion.links if not link.consistent]

    assert [(link.from_stage, link.to_stage) for link in inflating] == [
        ("papers_obtained", "draft_items")
    ]
    assert inflating[0].lost == 0
    assert inflating[0].rate == 40 / 7
    assert conversion.largest_drop_off not in inflating


def test_ties_go_to_the_earlier_link() -> None:
    report = _report(
        federated=20,
        plan=_plan(resolved=15, indexed=5, eligible=5),  # 20->15 loses 5; 15->10 loses 5
        acquisition=_acquisition(persisted=10, reused=0),
        extraction=_extraction(draft=10, classified=10, staged=10, grounded=10, promoted=10),
    )

    best = compute_funnel_conversion(report).largest_drop_off

    assert best is not None
    assert (best.from_stage, best.to_stage) == ("federated_candidates", "plan_resolved")


def test_a_link_nothing_entered_has_no_rate_not_zero_or_one() -> None:
    report = _report(federated=0, plan=_plan(resolved=0, indexed=0, eligible=0))

    first = compute_funnel_conversion(report).links[0]

    assert first.entered == 0
    assert first.rate is None
    assert first.consistent is True


def test_missing_stages_are_bridged_not_invented() -> None:
    report = _report(plan=None, acquisition=None, extraction=_extraction())

    stages = [(link.from_stage, link.to_stage) for link in compute_funnel_conversion(report).links]

    assert stages[0] == ("federated_candidates", "draft_items")
    assert len(stages) == 5


def test_discovery_not_triggered_leaves_federated_count_out() -> None:
    report = _report(discovery=False, federated=99, plan=_plan())

    stages = [link.from_stage for link in compute_funnel_conversion(report).links]

    assert "federated_candidates" not in stages
    assert stages == ["plan_resolved"]


def test_fewer_than_two_stages_gives_no_links_and_no_drop_off() -> None:
    conversion = compute_funnel_conversion(_report(discovery=True))

    assert conversion.links == ()
    assert conversion.largest_drop_off is None


def test_a_lossless_funnel_has_no_largest_drop_off() -> None:
    report = _report(
        federated=5,
        plan=_plan(resolved=5, indexed=2, eligible=3),
        acquisition=_acquisition(persisted=5, reused=0),
        extraction=_extraction(draft=5, classified=5, staged=5, grounded=5, promoted=5),
    )

    conversion = compute_funnel_conversion(report)

    assert all(link.lost == 0 for link in conversion.links)
    assert conversion.largest_drop_off is None


def test_result_serializes_to_json_with_the_drop_off() -> None:
    conversion: FunnelConversion = compute_funnel_conversion(_full())
    payload = json.loads(json.dumps(conversion.to_dict()))

    assert len(payload["links"]) == 8
    assert payload["largest_drop_off"]["to_stage"] == "classified"
    assert payload["links"][0] == {
        "from_stage": "federated_candidates",
        "to_stage": "plan_resolved",
        "entered": 12,
        "converted": 10,
        "lost": 2,
        "rate": 10 / 12,
        "consistent": True,
    }


def test_no_drop_off_serializes_as_null() -> None:
    assert compute_funnel_conversion(_report()).to_dict()["largest_drop_off"] is None
