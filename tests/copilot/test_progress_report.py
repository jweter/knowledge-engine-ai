from __future__ import annotations

import json
from dataclasses import dataclass

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import GroundedCompletionResult
from knowledge_engine_ai.copilot.intent import ISAValidationResult
from knowledge_engine_ai.copilot.progress_report import (
    RESEARCH_PROGRESS_REPORT_SCHEMA_VERSION,
    ResearchProgressStage,
    build_research_progress_report,
)
from knowledge_engine_ai.ke_client import FederatedDiscoveryResult, FederatedProviderStatus
from knowledge_engine_ai.models import (
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.bottleneck_report import ResearchPipelineStage
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.observability import EventTrace, SessionTrace
from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    ParallelRetrievalResult,
    RetrievalBranchResult,
)
from knowledge_engine_ai.orchestrator.session_report import SessionReport, SourcedClaim
from knowledge_engine_ai.orchestrator.verification import VerificationResult
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import SessionStatus


@dataclass(frozen=True)
class _Result:
    session_id: str
    workflow: WorkflowResult
    discovery: DiscoveryAugmentationResult | None
    close_result: SessionCloseResult
    narrative_releaseable: bool
    trace: SessionTrace
    grounded_completion: GroundedCompletionResult | None = None
    used_reretrieved_evidence: bool = False
    session_report: SessionReport | None = None
    effective_evidence_report: EvidenceReport | None = None


def _event(
    node: str, *, duration_ms: int | None = None, succeeded: bool = True
) -> EventTrace:
    return EventTrace(
        event_id=f"evt-{node}",
        workflow_node=node,
        executor_type="deterministic_tool",
        tool_name=None,
        model_name=None,
        succeeded=succeeded,
        duration_ms=duration_ms,
        notes=None,
        source_ids=(),
    )


def _trace(*, events: tuple[EventTrace, ...] = ()) -> SessionTrace:
    known = [event.duration_ms for event in events if event.duration_ms is not None]
    return SessionTrace(
        session_id="session-1",
        question="q",
        events=events,
        failed_events=tuple(event for event in events if not event.succeeded),
        total_duration_ms=sum(known) if known else None,
        evidence_record_ids=(),
    )


def _workflow(
    *, evidence_ids: tuple[str, ...] = (), primary_error: str | None = None
) -> WorkflowResult:
    primary = RetrievalBranchResult(query="q", report=None, error=primary_error)
    contradiction = RetrievalBranchResult(query="q contradiction", report=None, error=None)
    parallel = ParallelRetrievalResult(
        question="q",
        primary=primary,
        contradiction=contradiction,
        external_discovery_result=None,
        external_discovery_error=None,
        primary_evidence_record_ids=frozenset(evidence_ids),
        contradiction_evidence_record_ids=frozenset(),
        contradiction_only_evidence_record_ids=frozenset(),
    )
    return WorkflowResult(
        session_id="session-1",
        question="q",
        evidence_report=None,
        parallel_retrieval=parallel,
        steps=(),
    )


def _close(status: SessionStatus = SessionStatus.COMPLETED) -> SessionCloseResult:
    complete = status is SessionStatus.COMPLETED
    return SessionCloseResult(
        session_id="session-1",
        status=status,
        validation=ISAValidationResult(
            complete=complete,
            unresolved_required_criteria=() if complete else ("workflow_integrity",),
        ),
    )


def _provider_status(
    provider: str, *, outcome: str, attempted: bool = True, reason: str | None = None
) -> FederatedProviderStatus:
    return FederatedProviderStatus(
        provider=provider, outcome=outcome, attempted=attempted, result_count=0, reason=reason
    )


def _discovery(
    *,
    completeness: str = "complete",
    federated_attempted: bool = True,
    acquisition_attempted: bool = True,
    provider_statuses: tuple[FederatedProviderStatus, ...] = (),
) -> DiscoveryAugmentationResult:
    federated = FederatedDiscoveryResult(
        search_run_id="run-1",
        query_text="q",
        completeness=completeness,
        provider_statuses=provider_statuses,
        candidates=(),
        provider_disagreements=None,
        search_run_created_at=None,
    )
    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason="insufficient_evidence_record_coverage",
        evidence_record_coverage=1,
        federated_discovery=federated if federated_attempted else None,
        federated_discovery_attempted=federated_attempted,
        acquisition_plan_attempted=acquisition_attempted,
    )


def _completion(
    *, with_new_evidence: bool = True, attempted: bool = True
) -> GroundedCompletionResult:
    return GroundedCompletionResult(
        attempted=attempted,
        search_run_id="run-1",
        research_question_id="rq-1",
        paper_ids=(1,),
        promoted_record_ids=("ev-new",) if with_new_evidence else (),
        reretrieval_report=object() if with_new_evidence else None,  # type: ignore[arg-type]
    )


def _evidence_record(record_id: str, *, limitations: tuple[str, ...] = ()) -> EvidenceRecord:
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
        limitations=list(limitations),
        uncertainty_notes=None,
        confidence_note=None,
        source_span=None,
    )


def _evidence_report(records: tuple[EvidenceRecord, ...]) -> EvidenceReport:
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
        evidence_records=list(records),
    )
    return EvidenceReport(
        schema_version=1,
        question="q",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=1,
            draft=0,
            reviewed=1,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="ready.",
        ),
        papers=[paper],
        disclaimer="disclaimer",
    )


def _session_report(narrative: str, report: EvidenceReport) -> SessionReport:
    verification = VerificationResult(
        narrative=narrative,
        hallucinated_citations=(),
        ungrounded_numbers=(),
        missed_qualifiers=(),
    )
    sourced_claims = tuple(
        SourcedClaim(
            evidence_record_id=record.evidence_record_id,
            claim_text=record.claim_text,
            result_summary=record.result_summary,
            paper_title=paper.title,
            paper_authors=paper.authors,
            paper_year=paper.year,
            paper_doi=paper.doi,
            paper_citation=paper.citation,
            paper_source_url=paper.source_url,
        )
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id and f"[{record.evidence_record_id}]" in narrative
    )
    return SessionReport(
        narrative=narrative,
        sourced_claims=sourced_claims,
        unresolved_citations=(),
        verification=verification,
    )


# --- progress-stage mapping ---------------------------------------------------


def test_indexed_answer_is_final_answer_with_no_wait_reason() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1", "ev-2")),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
        )
    )

    assert report.schema_version == RESEARCH_PROGRESS_REPORT_SCHEMA_VERSION
    assert report.progress_stage is ResearchProgressStage.FINAL_ANSWER
    assert report.final is True
    assert report.wait_reason is None
    assert report.answer_available is True
    assert report.current_stage is ResearchPipelineStage.INDEXED_RETRIEVAL
    assert report.indexed_evidence_record_ids == ("ev-1", "ev-2")
    assert report.newly_acquired_evidence_record_ids == ()


def test_partial_answer_is_partial_answer_stage_not_final() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
        )
    )

    assert report.progress_stage is ResearchProgressStage.PARTIAL_ANSWER
    assert report.final is False
    assert report.wait_reason is None
    assert report.answer_available is True


def test_researched_answer_with_reretrieval_is_final_answer_at_reretrieval_stage() -> None:
    completion = _completion(with_new_evidence=True)
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
            grounded_completion=completion,
            used_reretrieved_evidence=True,
        )
    )

    assert report.progress_stage is ResearchProgressStage.FINAL_ANSWER
    assert report.current_stage is ResearchPipelineStage.RERETRIEVAL
    assert report.final is True
    assert report.newly_acquired_evidence_record_ids == ("ev-new",)


def test_provider_degraded_with_reretrieval_used_is_final_answer() -> None:
    completion = _completion(with_new_evidence=True)
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=_discovery(completeness="partial"),
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
            grounded_completion=completion,
            used_reretrieved_evidence=True,
        )
    )

    assert report.progress_stage is ResearchProgressStage.FINAL_ANSWER
    assert report.provider_degraded is True
    assert report.provider_coverage_completeness == "partial"


def test_provider_degraded_without_reretrieval_is_partial_answer() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=_discovery(completeness="partial"),
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
        )
    )

    assert report.progress_stage is ResearchProgressStage.PARTIAL_ANSWER
    assert report.provider_degraded is True


def test_blocked_primary_retrieval_failure_is_insufficient_evidence_at_indexed_retrieval() -> (
    None
):
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(primary_error="Core retrieval failed"),
            discovery=None,
            close_result=_close(SessionStatus.BLOCKED),
            narrative_releaseable=False,
            trace=_trace(),
        )
    )

    assert report.progress_stage is ResearchProgressStage.INSUFFICIENT_EVIDENCE
    assert report.research_state.value == "blocked"
    assert report.current_stage is ResearchPipelineStage.INDEXED_RETRIEVAL
    assert report.final is True


# --- product invariant (issue #90) --------------------------------------------


def test_zero_indexed_evidence_with_discovery_triggered_is_not_final_insufficient_evidence() -> (
    None
):
    """The BT-6 product invariant: `insufficient_evidence` must never be a stand-in for
    "initial indexed retrieval returned zero records." Discovery triggered, but this
    call never ran grounded completion -- the bounded research path has not actually
    finished, so this must resolve to `research_required`, not a final state.
    """

    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=()),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=False,
            trace=_trace(),
            grounded_completion=None,
        )
    )

    assert report.indexed_evidence_record_ids == ()
    assert report.progress_stage is ResearchProgressStage.RESEARCH_REQUIRED
    assert report.progress_stage is not ResearchProgressStage.INSUFFICIENT_EVIDENCE
    assert report.final is False
    assert report.wait_reason is not None


def test_zero_indexed_evidence_after_completed_bounded_research_is_final_insufficient_evidence() -> (
    None
):
    """Contrast case: only once the bounded research path actually completed (a
    `GroundedCompletionResult` exists) without producing a releaseable answer may this
    resolve to a *final* `insufficient_evidence`.
    """

    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=()),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=False,
            trace=_trace(),
            grounded_completion=_completion(with_new_evidence=False),
        )
    )

    assert report.progress_stage is ResearchProgressStage.INSUFFICIENT_EVIDENCE
    assert report.final is True
    assert report.wait_reason is None


def test_no_discovery_policy_and_zero_evidence_is_final_insufficient_evidence() -> None:
    """Corpus-only mode (no discovery policy supplied at all) never attempted bounded
    research in the first place, so its own zero-record result is honestly final --
    matching `research_state.py`'s existing, already-reviewed v1/v2 semantics. This
    is the one case where an immediate `insufficient_evidence` is correct: there was
    no research capability to attempt.
    """

    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=()),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=False,
            trace=_trace(),
        )
    )

    assert report.progress_stage is ResearchProgressStage.INSUFFICIENT_EVIDENCE
    assert report.final is True


# --- wait_reason detail ---------------------------------------------------------


def test_wait_reason_names_discovery_when_nothing_ran_yet() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(),
            discovery=DiscoveryAugmentationResult(
                triggered=True,
                trigger_reason="insufficient_evidence_record_coverage",
                evidence_record_coverage=0,
                federated_discovery_attempted=False,
                acquisition_plan_attempted=False,
            ),
            close_result=_close(),
            narrative_releaseable=False,
            trace=_trace(),
        )
    )

    assert report.progress_stage is ResearchProgressStage.RESEARCH_REQUIRED
    assert report.wait_reason is not None
    assert "discovery" in report.wait_reason.lower()


def test_wait_reason_names_grounded_completion_when_discovery_already_ran() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=False,
            trace=_trace(),
        )
    )

    assert report.progress_stage is ResearchProgressStage.RESEARCH_REQUIRED
    assert report.wait_reason is not None
    assert "grounded" in report.wait_reason.lower()


# --- provider coverage/degradation ----------------------------------------------


def test_provider_statuses_are_carried_through_for_web_rendering() -> None:
    statuses = (
        _provider_status("pubmed", outcome="success"),
        _provider_status("semantic_scholar", outcome="rate_limited", reason="429"),
    )
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=_discovery(completeness="partial", provider_statuses=statuses),
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
        )
    )

    assert report.provider_coverage_attempted is True
    assert report.provider_coverage_completeness == "partial"
    assert len(report.provider_statuses) == 2
    assert report.provider_statuses[1].provider == "semantic_scholar"
    assert report.provider_statuses[1].outcome == "rate_limited"
    assert report.provider_statuses[1].reason == "429"


def test_no_discovery_reports_provider_coverage_not_attempted() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
        )
    )

    assert report.provider_coverage_attempted is False
    assert report.provider_coverage_completeness is None
    assert report.provider_statuses == ()


# --- citations and limitations --------------------------------------------------


def test_citations_and_limitations_reflect_only_cited_records() -> None:
    cited = _evidence_record("ev-1", limitations=("small sample size",))
    uncited_qualifier = _evidence_record("ev-2", limitations=("short follow-up",))
    report_obj = _evidence_report((cited, uncited_qualifier))
    narrative = "Semaglutide reduced body weight [ev-1]."
    session_report = _session_report(narrative, report_obj)

    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
            session_report=session_report,
            effective_evidence_report=report_obj,
        )
    )

    assert [claim.evidence_record_id for claim in report.citations] == ["ev-1"]
    assert report.limitations == ("small sample size",)
    assert "short follow-up" not in report.limitations


def test_no_session_report_yields_empty_citations_and_limitations() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=False,
            trace=_trace(),
        )
    )

    assert report.citations == ()
    assert report.unresolved_citations == ()
    assert report.limitations == ()


# --- elapsed time / current stage / serialization -------------------------------


def test_elapsed_ms_uses_the_overlap_adjusted_bottleneck_total() -> None:
    events = (
        _event("retrieval_and_evidence_intelligence", duration_ms=100),
        _event("contradiction_oriented_retrieval", duration_ms=100),
        _event("synthesis", duration_ms=200),
    )
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(events=events),
        )
    )

    # The two parallel retrieval events must be counted once (max, not sum),
    # matching `bottleneck_report.py`'s own documented parallel-overlap rule.
    assert report.elapsed_ms == 300
    assert report.bottleneck_report.raw_event_duration_sum_ms == 400


def test_research_question_id_is_threaded_through_when_supplied() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(),
        ),
        research_question_id="rq-abc",
    )

    assert report.research_question_id == "rq-abc"


def test_to_json_serializes_every_enum_as_its_stable_string_value() -> None:
    report = build_research_progress_report(
        _Result(
            session_id="session-1",
            workflow=_workflow(evidence_ids=("ev-1", "ev-2")),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
            trace=_trace(events=(_event("retrieval_and_evidence_intelligence", duration_ms=10),)),
        )
    )

    payload = json.loads(report.to_json())
    assert payload["schema_version"] == RESEARCH_PROGRESS_REPORT_SCHEMA_VERSION
    assert payload["progress_stage"] == "final_answer"
    assert payload["current_stage"] == "indexed_retrieval"
    assert payload["research_state"] == "indexed_answer"
    assert payload["bottleneck_report"]["session_id"] == "session-1"
    assert isinstance(payload["bottleneck_report"]["slowest_stage"], (str, type(None)))


def test_all_nine_progress_stages_are_named_exactly_like_web_93() -> None:
    assert {stage.value for stage in ResearchProgressStage} == {
        "searching_indexed_evidence",
        "research_required",
        "discovering_sources",
        "acquiring_sources",
        "validating_extracting_evidence",
        "reretrieving",
        "partial_answer",
        "final_answer",
        "insufficient_evidence",
    }
