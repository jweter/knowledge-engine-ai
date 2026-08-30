from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import (
    AcquisitionRouteResult,
    GroundedCompletionResult,
)
from knowledge_engine_ai.copilot.progress_report import (
    ResearchProgressReport,
    ResearchProgressStage,
)
from knowledge_engine_ai.copilot.research_state import ResearchState
from knowledge_engine_ai.ke_client import (
    FederatedCandidateSummary,
    FederatedDiscoveryResult,
    GeneralQuestionAcquisitionPlanResult,
)
from knowledge_engine_ai.models import (
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.bottleneck_report import (
    ResearchPipelineStage,
    build_session_bottleneck_report,
)
from knowledge_engine_ai.orchestrator.funnel_report import (
    RESEARCH_CONVERSION_FUNNEL_SCHEMA_VERSION,
    build_research_conversion_funnel_report,
)
from knowledge_engine_ai.orchestrator.observability import EventTrace, SessionTrace


@dataclass(frozen=True)
class _Result:
    session_id: str
    discovery: DiscoveryAugmentationResult | None
    grounded_completion: GroundedCompletionResult | None
    progress_report: ResearchProgressReport | None


def _event(node: str, *, duration_ms: int | None) -> EventTrace:
    return EventTrace(
        event_id=f"evt-{node}",
        workflow_node=node,
        executor_type="deterministic_tool",
        tool_name=None,
        model_name=None,
        succeeded=True,
        duration_ms=duration_ms,
        notes=None,
        source_ids=(),
    )


def _progress(
    *,
    indexed_evidence_record_ids: tuple[str, ...] = (),
    newly_acquired_evidence_record_ids: tuple[str, ...] = (),
    events: tuple[EventTrace, ...] = (),
) -> ResearchProgressReport:
    known = [event.duration_ms for event in events if event.duration_ms is not None]
    trace = SessionTrace(
        session_id="session-1",
        question="q",
        events=events,
        failed_events=(),
        total_duration_ms=sum(known) if known else None,
        evidence_record_ids=(),
    )
    bottleneck = build_session_bottleneck_report(trace)
    return ResearchProgressReport(
        schema_version=1,
        session_id="session-1",
        research_question_id=None,
        progress_stage=ResearchProgressStage.FINAL_ANSWER,
        current_stage=ResearchPipelineStage.INDEXED_RETRIEVAL,
        research_state=ResearchState.INDEXED_ANSWER,
        research_state_reason="test",
        final=True,
        answer_available=True,
        wait_reason=None,
        elapsed_ms=bottleneck.adjusted_known_duration_ms,
        indexed_evidence_record_ids=indexed_evidence_record_ids,
        newly_acquired_evidence_record_ids=newly_acquired_evidence_record_ids,
        provider_coverage_attempted=False,
        provider_coverage_completeness=None,
        provider_degraded=False,
        provider_statuses=(),
        citations=(),
        unresolved_citations=(),
        limitations=(),
        bottleneck_report=bottleneck,
    )


def _acquisition_plan(
    *,
    resolved: int = 5,
    already_indexed: int = 1,
    full_text: int = 2,
    metadata_only: int = 1,
    skipped_budget: int = 1,
    missing: int = 0,
) -> GeneralQuestionAcquisitionPlanResult:
    return GeneralQuestionAcquisitionPlanResult(
        schema_version=1,
        search_run_id="run-1",
        research_question_id="rq-1",
        query_text="q",
        requested_candidate_count=resolved,
        resolved_candidate_count=resolved,
        already_indexed_count=already_indexed,
        full_text_selected_count=full_text,
        metadata_only_count=metadata_only,
        skipped_budget_count=skipped_budget,
        missing_candidate_count=missing,
        provider_failures=(),
        items=(),
    )


def _discovery(
    *,
    triggered: bool = True,
    candidate_count: int = 4,
    acquisition_plan: GeneralQuestionAcquisitionPlanResult | None = None,
) -> DiscoveryAugmentationResult:
    federated = FederatedDiscoveryResult(
        search_run_id="run-1",
        query_text="q",
        completeness="complete",
        provider_statuses=(),
        candidates=tuple(
            FederatedCandidateSummary(
                canonical_id=f"cand-{i}",
                title=f"Candidate {i}",
                doi=None,
                publication_year=None,
                providers=("pubmed",),
            )
            for i in range(candidate_count)
        ),
        provider_disagreements=None,
        search_run_created_at=None,
    )
    return DiscoveryAugmentationResult(
        triggered=triggered,
        trigger_reason="insufficient_evidence_record_coverage",
        evidence_record_coverage=0,
        federated_discovery=federated,
        federated_discovery_attempted=True,
        acquisition_plan=acquisition_plan,
        acquisition_plan_attempted=acquisition_plan is not None,
    )


def _evidence_record(record_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_record_id=record_id,
        extraction_method=None,
        extraction_status=None,
        review_status=None,
        review_checklist=None,
        review_notes=None,
        evidence_direction="supports",
        research_question=None,
        claim_text="claim",
        population=None,
        intervention=None,
        comparator=None,
        outcome=None,
        result_summary=None,
        limitations=[],
        uncertainty_notes=None,
        confidence_note=None,
        source_span=None,
    )


def _evidence_report(record_ids: tuple[str, ...]) -> EvidenceReport:
    paper = RetrievedPaper(
        rank=1,
        paper_id=1,
        title="T",
        authors="A",
        year="2026",
        journal="J",
        doi="10.1/x",
        source_url="https://example.org",
        license_type="CC BY",
        metadata_source="sources.csv",
        retrieval_score=1.0,
        retrieval_snippet="s",
        why_matched="m",
        citation="c",
        evidence_records=[_evidence_record(record_id) for record_id in record_ids],
    )
    return EvidenceReport(
        schema_version=1,
        question="q",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=len(record_ids),
            draft=0,
            reviewed=len(record_ids),
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="ready.",
        ),
        papers=[paper],
        disclaimer="disclaimer",
    )


def _completion(
    *,
    attempted: bool = True,
    paper_ids: tuple[int, ...] = (1, 2),
    routes: tuple[AcquisitionRouteResult, ...] = (),
    draft_item_count: int = 4,
    classified_item_count: int = 3,
    staged_record_ids: tuple[str, ...] = ("stg-1", "stg-2"),
    grounded_record_ids: tuple[str, ...] = ("stg-1",),
    promoted_record_ids: tuple[str, ...] = ("stg-1",),
    grounding_failures: tuple[str, ...] = ("stg-2",),
    reretrieval_report: EvidenceReport | None = None,
) -> GroundedCompletionResult:
    return GroundedCompletionResult(
        attempted=attempted,
        search_run_id="run-1",
        research_question_id="rq-1",
        acquisition_routes=routes,
        paper_ids=paper_ids,
        draft_item_count=draft_item_count,
        classified_item_count=classified_item_count,
        staged_record_ids=staged_record_ids,
        grounded_record_ids=grounded_record_ids,
        promoted_record_ids=promoted_record_ids,
        grounding_failures=grounding_failures,
        reretrieval_report=reretrieval_report,
    )


# --- missing progress_report -----------------------------------------------


def test_missing_progress_report_raises() -> None:
    with pytest.raises(ValueError, match="progress_report"):
        build_research_conversion_funnel_report(
            _Result(
                session_id="session-1",
                discovery=None,
                grounded_completion=None,
                progress_report=None,
            )
        )


# --- corpus-only path (no discovery, no completion) -------------------------


def test_corpus_only_path_has_no_discovery_or_completion_funnels() -> None:
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=None,
            grounded_completion=None,
            progress_report=_progress(indexed_evidence_record_ids=("ev-1", "ev-2")),
        )
    )

    assert report.schema_version == RESEARCH_CONVERSION_FUNNEL_SCHEMA_VERSION
    assert report.discovery_triggered is False
    assert report.federated_discovery_candidate_count == 0
    assert report.citation_snowball_candidate_count == 0
    assert report.acquisition_plan is None
    assert report.acquisition is None
    assert report.extraction is None
    assert report.reretrieval_attempted is False
    assert report.reretrieval_succeeded is False
    assert report.reretrieval_evidence_record_count == 0
    assert report.indexed_evidence_record_count == 2
    assert report.newly_promoted_evidence_record_count == 0


# --- discovery + acquisition-plan funnel ------------------------------------


def test_acquisition_plan_disposition_counts_are_carried_through() -> None:
    plan = _acquisition_plan(
        resolved=5, already_indexed=1, full_text=2, metadata_only=1, skipped_budget=1, missing=0
    )
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(candidate_count=4, acquisition_plan=plan),
            grounded_completion=None,
            progress_report=_progress(),
        )
    )

    assert report.discovery_triggered is True
    assert report.federated_discovery_candidate_count == 4
    assert report.acquisition_plan is not None
    assert report.acquisition_plan.resolved_candidate_count == 5
    assert report.acquisition_plan.already_indexed_count == 1
    assert report.acquisition_plan.full_text_eligible_count == 2
    assert report.acquisition_plan.metadata_only_count == 1
    assert report.acquisition_plan.skipped_budget_count == 1
    assert report.acquisition_plan.missing_candidate_count == 0
    # No grounded completion was attempted this run.
    assert report.acquisition is None
    assert report.extraction is None


# --- acquisition route funnel ------------------------------------------------


def test_acquisition_route_outcomes_are_counted() -> None:
    routes = (
        AcquisitionRouteResult(
            route="pmc_oa",
            candidate_ids=("c-1",),
            attempted=True,
            paper_ids=(1,),
            persisted_count=1,
            reused_count=0,
        ),
        AcquisitionRouteResult(
            route="europe_pmc_oa",
            candidate_ids=("c-2",),
            attempted=True,
            error="provider timeout",
        ),
        AcquisitionRouteResult(
            route="core",
            candidate_ids=("c-3",),
            attempted=False,
            skipped_reason="already-indexed evidence met the adequacy threshold",
        ),
    )
    completion = _completion(routes=routes)
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(),
        )
    )

    assert report.acquisition is not None
    assert report.acquisition.routes_attempted == 2
    assert report.acquisition.routes_skipped == 1
    assert report.acquisition.routes_failed == 1
    assert report.acquisition.papers_persisted == 1
    assert report.acquisition.papers_reused == 0


def test_acquisition_funnel_is_none_when_completion_not_attempted() -> None:
    completion = _completion(attempted=False, paper_ids=())
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(),
        )
    )

    assert report.acquisition is None
    assert report.extraction is None


# --- extraction funnel --------------------------------------------------------


def test_extraction_funnel_counts_and_derives_rejected_after_classification() -> None:
    completion = _completion(
        draft_item_count=4,
        classified_item_count=3,
        staged_record_ids=("stg-1", "stg-2"),
        grounded_record_ids=("stg-1",),
        promoted_record_ids=("stg-1",),
        grounding_failures=("stg-2",),
    )
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(),
        )
    )

    assert report.extraction is not None
    assert report.extraction.draft_item_count == 4
    assert report.extraction.classified_item_count == 3
    assert report.extraction.staged_record_count == 2
    assert report.extraction.grounded_record_count == 1
    assert report.extraction.promoted_record_count == 1
    assert report.extraction.grounding_failure_count == 1
    # 3 classified - 1 promoted = 2 rejected/dropped after classification.
    assert report.extraction.rejected_after_classification_count == 2


def test_rejected_after_classification_never_goes_negative() -> None:
    # Pathological/defensive case: promoted count should never exceed classified
    # count in practice, but the derivation must not report a negative funnel drop.
    completion = _completion(classified_item_count=1, promoted_record_ids=("a", "b"))
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(),
        )
    )

    assert report.extraction is not None
    assert report.extraction.rejected_after_classification_count == 0


# --- re-retrieval funnel -------------------------------------------------------


def test_reretrieval_succeeded_counts_records_in_the_reretrieved_report() -> None:
    reretrieved = _evidence_report(("ev-new-1", "ev-new-2"))
    completion = _completion(
        promoted_record_ids=("ev-new-1", "ev-new-2"), reretrieval_report=reretrieved
    )
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(),
        )
    )

    assert report.reretrieval_attempted is True
    assert report.reretrieval_succeeded is True
    assert report.reretrieval_evidence_record_count == 2
    assert report.newly_promoted_evidence_record_count == 2


def test_reretrieval_not_attempted_when_nothing_promoted() -> None:
    completion = _completion(
        promoted_record_ids=(), grounded_record_ids=(), reretrieval_report=None
    )
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(),
        )
    )

    assert report.reretrieval_attempted is False
    assert report.reretrieval_succeeded is False
    assert report.reretrieval_evidence_record_count == 0


# --- time-to-first-grounded-information / time-to-final-report ----------------


def test_time_to_first_grounded_information_uses_indexed_retrieval_when_available() -> None:
    events = (
        _event("retrieval_and_evidence_intelligence", duration_ms=120),
        _event("contradiction_oriented_retrieval", duration_ms=100),
        _event("synthesis", duration_ms=300),
    )
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=None,
            grounded_completion=None,
            progress_report=_progress(indexed_evidence_record_ids=("ev-1",), events=events),
        )
    )

    # Parallel retrieval overlap rule from bottleneck_report.py: max(120, 100) = 120.
    assert report.time_to_first_grounded_information_ms == 120
    assert report.time_to_final_report_ms == 420


def test_time_to_first_grounded_information_uses_reretrieval_when_no_indexed_evidence() -> None:
    events = (
        _event("retrieval_and_evidence_intelligence", duration_ms=50),
        _event("federated_discovery", duration_ms=200),
        _event("grounded_acquisition", duration_ms=400),
        _event("grounded_extraction", duration_ms=150),
        _event("grounded_reretrieval", duration_ms=80),
        _event("synthesis", duration_ms=60),
    )
    reretrieved = _evidence_report(("ev-new-1",))
    completion = _completion(promoted_record_ids=("ev-new-1",), reretrieval_report=reretrieved)
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(events=events),
        )
    )

    assert report.time_to_first_grounded_information_ms == 50 + 200 + 400 + 150 + 80
    assert report.time_to_final_report_ms == 50 + 200 + 400 + 150 + 80 + 60


def test_time_to_first_grounded_information_is_none_without_grounded_evidence() -> None:
    events = (_event("retrieval_and_evidence_intelligence", duration_ms=50),)
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=None,
            progress_report=_progress(events=events),
        )
    )

    assert report.time_to_first_grounded_information_ms is None


def test_time_to_first_grounded_information_is_none_when_reretrieval_report_is_empty() -> None:
    """Regression test for a Codex review finding on PR #125: `reretrieval_report
    is not None` alone does not mean grounded information was actually returned --
    a successful re-retrieval call can still come back with zero evidence records.
    The timing must gate on the evidence-record count, not command success alone.
    """

    events = (
        _event("retrieval_and_evidence_intelligence", duration_ms=50),
        _event("grounded_reretrieval", duration_ms=80),
    )
    empty_report = _evidence_report(())
    completion = _completion(promoted_record_ids=("ev-new-1",), reretrieval_report=empty_report)
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(),
            grounded_completion=completion,
            progress_report=_progress(events=events),
        )
    )

    assert report.reretrieval_succeeded is True
    assert report.reretrieval_evidence_record_count == 0
    assert report.time_to_first_grounded_information_ms is None


# --- serialization --------------------------------------------------------------


def test_to_json_round_trips_every_field() -> None:
    plan = _acquisition_plan()
    completion = _completion()
    report = build_research_conversion_funnel_report(
        _Result(
            session_id="session-1",
            discovery=_discovery(acquisition_plan=plan),
            grounded_completion=completion,
            progress_report=_progress(indexed_evidence_record_ids=("ev-1",)),
        )
    )

    payload = json.loads(report.to_json())
    assert payload["schema_version"] == RESEARCH_CONVERSION_FUNNEL_SCHEMA_VERSION
    assert payload["session_id"] == "session-1"
    assert payload["acquisition_plan"]["resolved_candidate_count"] == 5
    assert payload["extraction"]["promoted_record_count"] == 1
    assert payload["indexed_evidence_record_count"] == 1
