"""Stable workflow-state metadata for General Question Research Loop v1.

The state in this module describes *what the bounded research workflow did*;
it is not a scientific confidence score.  Derivation uses only deterministic
retrieval, discovery, acquisition-plan, close-gate, and release-gate outcomes
that already exist on ``ResearchQuestionResult``.  Provider count is never
used as a quality proxy and discovery candidates are never treated as evidence.

The current Research Copilot call is synchronous, so ``RESEARCHING`` is part of
the public schema for the later durable/polling workflow but is not emitted by
``derive_research_state`` yet.  A future asynchronous orchestrator may emit it
while acquisition/extraction is genuinely still in progress.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import SessionStatus

RESEARCH_STATE_SCHEMA_VERSION = 1


class ResearchState(StrEnum):
    """Stable General Question Research Loop workflow states."""

    INDEXED_ANSWER = "indexed_answer"
    RESEARCH_REQUIRED = "research_required"
    RESEARCHING = "researching"
    PARTIAL_ANSWER = "partial_answer"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    PROVIDER_DEGRADED = "provider_degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ResearchStateResult:
    """Serializable deterministic state plus the facts used to derive it."""

    schema_version: int
    state: ResearchState
    reason: str
    indexed_evidence_record_count: int
    discovery_triggered: bool
    federated_discovery_attempted: bool
    acquisition_plan_attempted: bool
    provider_degraded: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class ResearchResultLike(Protocol):
    """Minimal completed-result surface required for deterministic state derivation."""

    @property
    def workflow(self) -> WorkflowResult: ...

    @property
    def discovery(self) -> DiscoveryAugmentationResult | None: ...

    @property
    def close_result(self) -> SessionCloseResult: ...

    @property
    def narrative_releaseable(self) -> bool: ...


def derive_research_state(result: ResearchResultLike) -> ResearchStateResult:
    """Derive one stable GQR state from already-recorded deterministic outcomes.

    This function deliberately does not inspect narrative text, ask an LLM, or
    infer provider success from candidate/result counts.  A triggered discovery
    run cannot be labeled ``indexed_answer`` because its own deterministic
    adequacy rule already established that indexed coverage was insufficient.
    Until grounded acquisition/extraction/re-retrieval exists, a releaseable
    narrative after such a trigger is therefore at most ``partial_answer``.
    """

    evidence_count = _indexed_evidence_record_count(result.workflow)
    discovery = result.discovery
    triggered = bool(discovery and discovery.triggered)
    federated_attempted = bool(discovery and discovery.federated_discovery_attempted)
    acquisition_attempted = bool(discovery and discovery.acquisition_plan_attempted)
    degraded = _provider_degraded(discovery)

    if _primary_retrieval_failed(result.workflow):
        return _state(
            ResearchState.BLOCKED,
            "primary_retrieval_failed",
            evidence_count,
            triggered,
            federated_attempted,
            acquisition_attempted,
            degraded,
        )

    if result.close_result.status is SessionStatus.BLOCKED:
        return _state(
            ResearchState.BLOCKED,
            "required_release_gate_failed",
            evidence_count,
            triggered,
            federated_attempted,
            acquisition_attempted,
            degraded,
        )

    if not triggered:
        if result.narrative_releaseable:
            return _state(
                ResearchState.INDEXED_ANSWER,
                "indexed_evidence_sufficient",
                evidence_count,
                False,
                federated_attempted,
                acquisition_attempted,
                degraded,
            )
        return _state(
            ResearchState.INSUFFICIENT_EVIDENCE,
            "no_releaseable_grounded_indexed_answer",
            evidence_count,
            False,
            federated_attempted,
            acquisition_attempted,
            degraded,
        )

    if result.narrative_releaseable:
        if degraded:
            return _state(
                ResearchState.PROVIDER_DEGRADED,
                "releaseable_partial_answer_with_degraded_provider_coverage",
                evidence_count,
                True,
                federated_attempted,
                acquisition_attempted,
                True,
            )
        return _state(
            ResearchState.PARTIAL_ANSWER,
            "indexed_coverage_was_insufficient_and_new_leads_are_not_yet_evidence",
            evidence_count,
            True,
            federated_attempted,
            acquisition_attempted,
            False,
        )

    return _state(
        ResearchState.RESEARCH_REQUIRED,
        (
            "indexed_coverage_insufficient_bounded_research_started"
            if federated_attempted or acquisition_attempted
            else "indexed_coverage_insufficient_bounded_research_required"
        ),
        evidence_count,
        True,
        federated_attempted,
        acquisition_attempted,
        degraded,
    )


def _state(
    state: ResearchState,
    reason: str,
    evidence_count: int,
    triggered: bool,
    federated_attempted: bool,
    acquisition_attempted: bool,
    degraded: bool,
) -> ResearchStateResult:
    return ResearchStateResult(
        schema_version=RESEARCH_STATE_SCHEMA_VERSION,
        state=state,
        reason=reason,
        indexed_evidence_record_count=evidence_count,
        discovery_triggered=triggered,
        federated_discovery_attempted=federated_attempted,
        acquisition_plan_attempted=acquisition_attempted,
        provider_degraded=degraded,
    )


def _primary_retrieval_failed(workflow: WorkflowResult) -> bool:
    parallel = workflow.parallel_retrieval
    return parallel is not None and parallel.primary.error is not None


def _indexed_evidence_record_count(workflow: WorkflowResult) -> int:
    parallel = workflow.parallel_retrieval
    if parallel is not None:
        return len(
            parallel.primary_evidence_record_ids | parallel.contradiction_evidence_record_ids
        )
    report = workflow.evidence_report
    if report is None:
        return 0
    return len(
        {
            record.evidence_record_id
            for paper in report.papers
            for record in paper.evidence_records
            if record.evidence_record_id
        }
    )


def _provider_degraded(discovery: DiscoveryAugmentationResult | None) -> bool:
    if discovery is None:
        return False
    if discovery.federated_discovery_error is not None:
        return True
    federated = discovery.federated_discovery
    return federated is not None and federated.completeness != "complete"


__all__ = [
    "RESEARCH_STATE_SCHEMA_VERSION",
    "ResearchState",
    "ResearchStateResult",
    "derive_research_state",
]
