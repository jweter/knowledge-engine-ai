from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import (
    AcquisitionRouteResult,
    GroundedCompletionResult,
)
from knowledge_engine_ai.copilot.intent import ISAValidationResult
from knowledge_engine_ai.ke_client import (
    FederatedCandidateSummary,
    FederatedDiscoveryResult,
    FederatedProviderStatus,
)
from knowledge_engine_ai.models import EvidenceReport, parse_evidence_report
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.observability import EventTrace, SessionTrace
from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    ParallelRetrievalResult,
    RetrievalBranchResult,
)
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.research_pipeline_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    build_research_benchmark_run,
    compute_evidence_store_revision,
    execute_research_benchmark,
)
from knowledge_engine_ai.sessions.models import SessionStatus

QUESTION = (
    "In healthy adults, does listening to music during exercise improve endurance "
    "performance compared with exercising without music?"
)


@dataclass(frozen=True)
class _Result:
    session_id: str
    question: str
    workflow: WorkflowResult
    discovery: DiscoveryAugmentationResult | None
    grounded_completion: GroundedCompletionResult | None
    close_result: SessionCloseResult
    trace: SessionTrace
    narrative_releaseable: bool
    used_reretrieved_evidence: bool


def _report() -> EvidenceReport:
    return parse_evidence_report(
        {
            "schema_version": 1,
            "question": QUESTION,
            "sources_path": "sources.csv",
            "evidence_path": "evidence.jsonl",
            "evidence_summary": {
                "total": 1,
                "draft": 0,
                "reviewed": 1,
                "needs_revision": 0,
                "rejected": 0,
                "unspecified": 0,
                "readiness_note": "ready",
            },
            "papers": [
                {
                    "rank": 1,
                    "paper_id": 12,
                    "title": "Music and endurance",
                    "authors": "A. Researcher",
                    "year": "2024",
                    "journal": "Exercise Journal",
                    "doi": "10.1000/music-endurance",
                    "source_url": "https://example.org/paper",
                    "license_type": "CC BY",
                    "metadata_source": "sources.csv",
                    "retrieval_score": -1.0,
                    "retrieval_snippet": "Music improved time to exhaustion.",
                    "why_matched": "matched",
                    "citation": "A. Researcher (2024)",
                    "evidence_records": [
                        {
                            "evidence_record_id": "ev-music-1",
                            "claim_text": "Music improved time to exhaustion.",
                            "evidence_direction": "supports",
                        }
                    ],
                }
            ],
            "disclaimer": "retrieval plus recorded evidence only",
        }
    )


def _workflow(*, indexed_ids: tuple[str, ...]) -> WorkflowResult:
    primary = RetrievalBranchResult(query=QUESTION, report=None, error=None)
    contradiction = RetrievalBranchResult(query=f"{QUESTION} contradiction", report=None, error=None)
    parallel = ParallelRetrievalResult(
        question=QUESTION,
        primary=primary,
        contradiction=contradiction,
        external_discovery_result=None,
        external_discovery_error=None,
        primary_evidence_record_ids=frozenset(indexed_ids),
        contradiction_evidence_record_ids=frozenset(),
        contradiction_only_evidence_record_ids=frozenset(),
    )
    return WorkflowResult(
        session_id="workflow-session",
        question=QUESTION,
        evidence_report=None,
        parallel_retrieval=parallel,
        steps=(),
    )


def _discovery() -> DiscoveryAugmentationResult:
    federated = FederatedDiscoveryResult(
        search_run_id="search-run-music",
        query_text=QUESTION,
        completeness="partial",
        provider_statuses=(
            FederatedProviderStatus(
                provider="pubmed",
                outcome="success",
                attempted=True,
                result_count=4,
                reason=None,
            ),
            FederatedProviderStatus(
                provider="semantic_scholar",
                outcome="failed",
                attempted=True,
                result_count=0,
                reason="rate limited",
            ),
        ),
        candidates=(
            FederatedCandidateSummary(
                canonical_id="doi:10.1000/music-endurance",
                title="Music and endurance",
                doi="10.1000/music-endurance",
                publication_year=2024,
                providers=("pubmed",),
            ),
            FederatedCandidateSummary(
                canonical_id="pmid:12345",
                title="Exercise music trial",
                doi=None,
                publication_year=2021,
                providers=("pubmed",),
            ),
        ),
        provider_disagreements=None,
        search_run_created_at="2026-08-28T11:00:00Z",
    )
    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason="insufficient_evidence_record_coverage",
        evidence_record_coverage=0,
        federated_discovery=federated,
        federated_discovery_attempted=True,
        acquisition_plan_attempted=True,
    )


def _completion(*, reuse: bool = False) -> GroundedCompletionResult:
    return GroundedCompletionResult(
        attempted=True,
        search_run_id="search-run-music",
        research_question_id="rq-music",
        already_indexed_paper_ids=(12,) if reuse else (),
        acquisition_routes=(
            AcquisitionRouteResult(
                route="pmc_oa",
                candidate_ids=("doi:10.1000/music-endurance",),
                attempted=True,
                paper_ids=(12,),
                import_run_id="import-1",
                persisted_count=0 if reuse else 1,
                reused_count=1 if reuse else 0,
            ),
        ),
        paper_ids=(12,),
        draft_item_count=3,
        classified_item_count=2,
        staged_record_ids=("ev-music-1",),
        grounded_record_ids=("ev-music-1",),
        promoted_record_ids=("ev-music-1",),
        reretrieval_report=_report(),
    )


def _trace() -> SessionTrace:
    events = (
        EventTrace(
            event_id="retrieval",
            workflow_node="retrieval_and_evidence_intelligence",
            executor_type="deterministic_tool",
            tool_name="ke evidence-report",
            model_name=None,
            succeeded=True,
            duration_ms=200,
            notes=None,
            source_ids=(),
        ),
        EventTrace(
            event_id="contradiction",
            workflow_node="contradiction_oriented_retrieval",
            executor_type="deterministic_tool",
            tool_name="ke evidence-report",
            model_name=None,
            succeeded=True,
            duration_ms=200,
            notes=None,
            source_ids=(),
        ),
        EventTrace(
            event_id="discovery",
            workflow_node="federated_discovery",
            executor_type="deterministic_tool",
            tool_name="ke federated-discover",
            model_name=None,
            succeeded=True,
            duration_ms=500,
            notes=None,
            source_ids=(),
        ),
        EventTrace(
            event_id="acquisition",
            workflow_node="grounded_acquisition",
            executor_type="deterministic_tool",
            tool_name="ke general-question-acquire-pmc",
            model_name=None,
            succeeded=True,
            duration_ms=700,
            notes=None,
            source_ids=(),
        ),
        EventTrace(
            event_id="extraction",
            workflow_node="grounded_extraction",
            executor_type="deterministic_tool",
            tool_name="ke evidence-review-automate",
            model_name=None,
            succeeded=True,
            duration_ms=900,
            notes=None,
            source_ids=(),
        ),
        EventTrace(
            event_id="reretrieval",
            workflow_node="grounded_reretrieval",
            executor_type="deterministic_tool",
            tool_name="ke evidence-report",
            model_name=None,
            succeeded=True,
            duration_ms=250,
            notes=None,
            source_ids=("ev-music-1",),
        ),
        EventTrace(
            event_id="synthesis",
            workflow_node="synthesis",
            executor_type="local_llm",
            tool_name=None,
            model_name="test-model",
            succeeded=True,
            duration_ms=300,
            notes=None,
            source_ids=("ev-music-1",),
        ),
    )
    return SessionTrace(
        session_id="session-music",
        question=QUESTION,
        events=events,
        failed_events=(),
        total_duration_ms=sum(event.duration_ms or 0 for event in events),
        evidence_record_ids=("ev-music-1",),
    )


def _close() -> SessionCloseResult:
    return SessionCloseResult(
        session_id="session-music",
        status=SessionStatus.COMPLETED,
        validation=ISAValidationResult(complete=True, unresolved_required_criteria=()),
    )


def _result(*, reuse: bool = False) -> _Result:
    return _Result(
        session_id="session-music",
        question=QUESTION,
        workflow=_workflow(indexed_ids=()),
        discovery=_discovery(),
        grounded_completion=_completion(reuse=reuse),
        close_result=_close(),
        trace=_trace(),
        narrative_releaseable=True,
        used_reretrieved_evidence=True,
    )


def test_benchmark_projects_research_funnel_and_bottleneck_report() -> None:
    run = build_research_benchmark_run(
        _result(),
        scenario_id="fresh-music-endurance",
        run_number=1,
        run_temperature="cold",
        wall_clock_duration_ms=3100,
        evidence_store_revision="sha256:before",
    )

    assert run.schema_version == BENCHMARK_SCHEMA_VERSION
    assert run.final_state.state.value == "provider_degraded"
    assert run.used_reretrieved_evidence is True
    assert run.funnel.provider_attempt_count == 2
    assert run.funnel.provider_degraded_count == 1
    assert run.funnel.discovery_candidate_count == 2
    assert run.funnel.acquisition_route_attempt_count == 1
    assert run.funnel.persisted_paper_count == 1
    assert run.funnel.promoted_evidence_record_count == 1
    assert run.funnel.reretrieval_attempt_count == 1
    assert run.known_time_to_first_grounded_information_ms == 2550
    assert run.bottleneck_report.slowest_stage is not None
    assert run.bottleneck_report.slowest_stage.value == "extraction_promotion"


def test_repeat_suite_reports_speedup_and_reuse() -> None:
    results = iter((_result(), _result(reuse=True)))
    ticks = iter((10.0, 14.0, 20.0, 22.0))

    suite = execute_research_benchmark(
        QUESTION,
        scenario_id="fresh-music-endurance",
        run_once=lambda question: next(results),
        repeats=2,
        evidence_store_revision=lambda: "sha256:test",
        clock=lambda: next(ticks),
    )

    assert [run.run_temperature for run in suite.runs] == ["cold", "warm"]
    assert [run.wall_clock_duration_ms for run in suite.runs] == [4000, 2000]
    assert suite.repeat_speedup_ratio == 2.0
    assert suite.warm_run_reuse_observed is True
    assert suite.runs[1].funnel.reuse_hit is True
    assert suite.to_dict()["run_count"] == 2


def test_unknown_or_untimed_grounded_stage_keeps_first_information_time_unknown() -> None:
    trace = _trace()
    events = tuple(
        EventTrace(
            event_id=event.event_id,
            workflow_node=event.workflow_node,
            executor_type=event.executor_type,
            tool_name=event.tool_name,
            model_name=event.model_name,
            succeeded=event.succeeded,
            duration_ms=None if event.workflow_node == "grounded_extraction" else event.duration_ms,
            notes=event.notes,
            source_ids=event.source_ids,
        )
        for event in trace.events
    )
    result = _result()
    result = _Result(
        session_id=result.session_id,
        question=result.question,
        workflow=result.workflow,
        discovery=result.discovery,
        grounded_completion=result.grounded_completion,
        close_result=result.close_result,
        trace=SessionTrace(
            session_id=trace.session_id,
            question=trace.question,
            events=events,
            failed_events=(),
            total_duration_ms=sum(event.duration_ms or 0 for event in events),
            evidence_record_ids=trace.evidence_record_ids,
        ),
        narrative_releaseable=result.narrative_releaseable,
        used_reretrieved_evidence=result.used_reretrieved_evidence,
    )

    run = build_research_benchmark_run(
        result,
        scenario_id="fresh-music-endurance",
        run_number=1,
        run_temperature="cold",
        wall_clock_duration_ms=3100,
    )

    assert run.known_time_to_first_grounded_information_ms is None
    assert run.bottleneck_report.timing_complete is False
    assert run.bottleneck_report.untimed_event_ids == ("extraction",)


def test_evidence_revision_is_content_addressed(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text('{"evidence_record_id":"ev-1"}\n', encoding="utf-8")

    first = compute_evidence_store_revision(evidence)
    second = compute_evidence_store_revision(evidence)

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64


def test_benchmark_rejects_invalid_execution_contracts() -> None:
    with pytest.raises(ValueError, match="question must be non-blank"):
        execute_research_benchmark(" ", scenario_id="x", run_once=lambda question: _result())

    with pytest.raises(ValueError, match="repeats must be at least 1"):
        execute_research_benchmark(
            QUESTION,
            scenario_id="x",
            run_once=lambda question: _result(),
            repeats=0,
        )
