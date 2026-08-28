"""Stable workflow-state metadata for General Question Research Loop v1.

The state in this module describes *what the bounded research workflow did*;
it is not a scientific confidence score. Derivation uses only deterministic
retrieval, discovery, grounded-completion, close-gate, and release-gate facts
already recorded on ``ResearchQuestionResult``. Provider count is never used
as a quality proxy and discovery candidates are never treated as evidence.

The current Research Copilot call is synchronous, so ``RESEARCHING`` remains
part of the public schema for a later durable/polling workflow but is not
emitted by ``derive_research_state`` yet.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import GroundedCompletionResult
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import SessionStatus

RESEARCH_STATE_SCHEMA_VERSION = 2


class ResearchState(StrEnum):
    """Stable General Question Research Loop workflow states."""

    INDEXED_ANSWER = "indexed_answer"
    RESEARCH_REQUIRED = "research_required"
    RESEARCHING = "researching"
    PARTIAL_ANSWER = "partial_answer"
    RESEARCHED_ANSWER = "researched_answer"
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
    grounded_completion_attempted: bool
    grounded_completion_completed: bool
    used_reretrieved_evidence: bool
    promoted_evidence_record_count: int
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
    def grounded_completion(self) -> GroundedCompletionResult | None: ...

    @property
    def used_reretrieved_evidence(self) -> bool: ...

    @property
    def close_result(self) -> SessionCloseResult: ...

    @property
    def narrative_releaseable(self) -> bool: ...


def derive_research_state(result: ResearchResultLike) -> ResearchStateResult:
    """Derive one stable GQR state from already-recorded deterministic outcomes.

    A triggered discovery run cannot be labeled ``indexed_answer`` because its
    own adequacy rule already established that indexed coverage was insufficient.
    Once grounded completion promotes evidence, re-runs the original question,
    and that reretrieved report is actually used for a releaseable narrative,
    the result is ``researched_answer``. A fully evaluated bounded research path
    that produces no releaseable grounded answer is ``insufficient_evidence``;
    it is no longer left in ``research_required`` merely because the initial
    corpus was thin.
    """

    evidence_count = _indexed_evidence_record_count(result.workflow)
    discovery = result.discovery
    completion = result.grounded_completion
    triggered = bool(discovery and discovery.triggered)
    federated_attempted = bool(discovery and discovery.federated_discovery_attempted)
    acquisition_attempted = bool(discovery and discovery.acquisition_plan_attempted)
    completion_attempted = bool(completion and completion.attempted)
    completion_completed = bool(completion and completion.completed_with_new_evidence)
    used_reretrieved = bool(result.used_reretrieved_evidence)
    promoted_count = len(completion.promoted_record_ids) if completion is not None else 0
    degraded = _provider_degraded(discovery)

    facts = _Facts(
        evidence_count=evidence_count,
        triggered=triggered,
        federated_attempted=federated_attempted,
        acquisition_attempted=acquisition_attempted,
        completion_attempted=completion_attempted,
        completion_completed=completion_completed,
        used_reretrieved=used_reretrieved,
        promoted_count=promoted_count,
        degraded=degraded,
    )

    if _primary_retrieval_failed(result.workflow):
        return _state(ResearchState.BLOCKED, "primary_retrieval_failed", facts)

    if result.close_result.status is SessionStatus.BLOCKED:
        return _state(ResearchState.BLOCKED, "required_release_gate_failed", facts)

    if not triggered:
        if result.narrative_releaseable:
            return _state(ResearchState.INDEXED_ANSWER, "indexed_evidence_sufficient", facts)
        return _state(
            ResearchState.INSUFFICIENT_EVIDENCE,
            "no_releaseable_grounded_indexed_answer",
            facts,
        )

    if result.narrative_releaseable:
        if degraded:
            reason = (
                "releaseable_researched_answer_with_degraded_provider_coverage"
                if used_reretrieved and completion_completed
                else "releaseable_partial_answer_with_degraded_provider_coverage"
            )
            return _state(ResearchState.PROVIDER_DEGRADED, reason, facts)
        if used_reretrieved and completion_completed:
            return _state(
                ResearchState.RESEARCHED_ANSWER,
                "grounded_completion_reretrieval_used_for_releaseable_answer",
                facts,
            )
        return _state(
            ResearchState.PARTIAL_ANSWER,
            "indexed_coverage_was_insufficient_and_new_leads_are_not_yet_evidence",
            facts,
        )

    if completion is not None:
        return _state(
            ResearchState.INSUFFICIENT_EVIDENCE,
            "bounded_research_completed_without_releaseable_grounded_answer",
            facts,
        )

    return _state(
        ResearchState.RESEARCH_REQUIRED,
        (
            "indexed_coverage_insufficient_bounded_research_started"
            if federated_attempted or acquisition_attempted
            else "indexed_coverage_insufficient_bounded_research_required"
        ),
        facts,
    )


@dataclass(frozen=True)
class _Facts:
    evidence_count: int
    triggered: bool
    federated_attempted: bool
    acquisition_attempted: bool
    completion_attempted: bool
    completion_completed: bool
    used_reretrieved: bool
    promoted_count: int
    degraded: bool


def _state(state: ResearchState, reason: str, facts: _Facts) -> ResearchStateResult:
    return ResearchStateResult(
        schema_version=RESEARCH_STATE_SCHEMA_VERSION,
        state=state,
        reason=reason,
        indexed_evidence_record_count=facts.evidence_count,
        discovery_triggered=facts.triggered,
        federated_discovery_attempted=facts.federated_attempted,
        acquisition_plan_attempted=facts.acquisition_attempted,
        grounded_completion_attempted=facts.completion_attempted,
        grounded_completion_completed=facts.completion_completed,
        used_reretrieved_evidence=facts.used_reretrieved,
        promoted_evidence_record_count=facts.promoted_count,
        provider_degraded=facts.degraded,
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
