from __future__ import annotations

import json
from dataclasses import dataclass

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.intent import ISAValidationResult
from knowledge_engine_ai.copilot.research_state import (
    RESEARCH_STATE_SCHEMA_VERSION,
    ResearchState,
    derive_research_state,
)
from knowledge_engine_ai.ke_client import FederatedDiscoveryResult
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    ParallelRetrievalResult,
    RetrievalBranchResult,
)
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import SessionStatus


@dataclass(frozen=True)
class _Result:
    workflow: WorkflowResult
    discovery: DiscoveryAugmentationResult | None
    close_result: SessionCloseResult
    narrative_releaseable: bool


def _workflow(*, evidence_ids: tuple[str, ...] = (), primary_error: str | None = None) -> WorkflowResult:
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


def _discovery(*, completeness: str = "complete") -> DiscoveryAugmentationResult:
    federated = FederatedDiscoveryResult(
        search_run_id="run-1",
        query_text="q",
        completeness=completeness,
        provider_statuses=(),
        candidates=(),
        provider_disagreements=None,
        search_run_created_at=None,
    )
    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason="insufficient_evidence_record_coverage",
        evidence_record_coverage=1,
        federated_discovery=federated,
        federated_discovery_attempted=True,
        acquisition_plan_attempted=False,
    )


def test_indexed_releaseable_answer_is_indexed_answer_and_serializes_stably() -> None:
    state = derive_research_state(
        _Result(
            workflow=_workflow(evidence_ids=("ev-1", "ev-2")),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=True,
        )
    )

    assert state.state is ResearchState.INDEXED_ANSWER
    assert state.indexed_evidence_record_count == 2
    assert state.discovery_triggered is False
    assert state.schema_version == RESEARCH_STATE_SCHEMA_VERSION
    assert json.loads(state.to_json()) == {
        "acquisition_plan_attempted": False,
        "discovery_triggered": False,
        "federated_discovery_attempted": False,
        "indexed_evidence_record_count": 2,
        "provider_degraded": False,
        "reason": "indexed_evidence_sufficient",
        "schema_version": 1,
        "state": "indexed_answer",
    }


def test_triggered_research_with_releaseable_indexed_evidence_is_partial() -> None:
    state = derive_research_state(
        _Result(
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=True,
        )
    )

    assert state.state is ResearchState.PARTIAL_ANSWER
    assert state.discovery_triggered is True
    assert state.federated_discovery_attempted is True


def test_releaseable_answer_with_degraded_provider_coverage_is_provider_degraded() -> None:
    state = derive_research_state(
        _Result(
            workflow=_workflow(evidence_ids=("ev-1",)),
            discovery=_discovery(completeness="partial"),
            close_result=_close(),
            narrative_releaseable=True,
        )
    )

    assert state.state is ResearchState.PROVIDER_DEGRADED
    assert state.provider_degraded is True


def test_triggered_research_without_releaseable_answer_remains_research_required() -> None:
    state = derive_research_state(
        _Result(
            workflow=_workflow(),
            discovery=_discovery(),
            close_result=_close(),
            narrative_releaseable=False,
        )
    )

    assert state.state is ResearchState.RESEARCH_REQUIRED
    assert state.reason == "indexed_coverage_insufficient_bounded_research_started"


def test_no_trigger_and_no_releaseable_answer_is_insufficient_evidence() -> None:
    state = derive_research_state(
        _Result(
            workflow=_workflow(),
            discovery=None,
            close_result=_close(),
            narrative_releaseable=False,
        )
    )

    assert state.state is ResearchState.INSUFFICIENT_EVIDENCE


def test_primary_retrieval_failure_is_blocked_even_when_discovery_metadata_exists() -> None:
    state = derive_research_state(
        _Result(
            workflow=_workflow(primary_error="Core retrieval failed"),
            discovery=_discovery(completeness="partial"),
            close_result=_close(SessionStatus.BLOCKED),
            narrative_releaseable=False,
        )
    )

    assert state.state is ResearchState.BLOCKED
    assert state.reason == "primary_retrieval_failed"


def test_researching_state_is_reserved_in_stable_schema_for_async_progress() -> None:
    assert ResearchState.RESEARCHING.value == "researching"
