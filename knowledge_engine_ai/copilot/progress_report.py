"""BT-6: stable progressive research report contract for Web.

Issue #90's goal is to give Web a structured signal it can render *while a
question is in flight or once it finishes* instead of stopping at the first
local corpus miss (issue #84/#89 and `knowledge-engine-web#93`'s "never
terminate on the initial corpus miss"). This module is a pure read-side
projection -- the same posture `research_state.py` and `bottleneck_report.py`
already established -- over facts `run_research_question` already computed.
It derives nothing new about evidence quality, adequacy, or release
eligibility; it only re-expresses already-deterministic facts in the shape
Web's 8 named progress states (`knowledge-engine-web#93`) need.

## Product invariant (issue #90)

``insufficient_evidence`` must be a *final* research outcome, never a
synonym for "the initial indexed retrieval returned zero records." This
module never derives its own adequacy judgment -- it reuses
`research_state.derive_research_state`, whose v2 schema already encodes the
invariant correctly (`docs/roadmap/gqr_research_state_v2.md`): a session
that triggered bounded research but has not yet run grounded completion
stays `research_required`, not `insufficient_evidence`, and only a
*completed* bounded pass (a `GroundedCompletionResult` exists) can resolve
to `insufficient_evidence`. `ResearchProgressReport.final` makes that same
gate directly checkable by a caller without re-deriving `ResearchState`
branch logic itself.

## Mapping onto Web's 8 progress states

`ResearchProgressStage` names the same 8 states `knowledge-engine-web#93`
lists, so Web can render this field close to verbatim. The synchronous,
single-shot `run_research_question` call this module is wired into only
ever *returns* after the bounded pipeline has already finished one full
pass, so a report built from its result can only ever resolve to one of
the states that describe a completed call:
``research_required``, ``partial_answer``, ``final_answer``, or
``insufficient_evidence``. `searching_indexed_evidence`, `discovering_sources`,
`acquiring_sources`, `validating_extracting_evidence`, and `reretrieving`
are reserved in this schema for a later durable/incremental caller that
builds a report mid-flight from partial facts -- the same
"reserved but not yet emitted" precedent `research_state.ResearchState.RESEARCHING`
already set. Building that incremental caller is out of scope for this
slice; see `docs/roadmap/bt6_progressive_report_contract.md`.

## What this does not do

It does not call an LLM, does not treat discovery candidates as evidence,
does not invent a percent-complete estimate (`research_pipeline_bottlenecks.md`
explicitly warns against fake progress bars), and does not change retrieval,
discovery, grounded-completion, or release-gate behavior. `wait_reason` is
honest about the synchronous architecture: for a `research_required` result
it names what a *follow-up call* would need to opt into next (e.g. supplying
`grounded_completion_policy`), not a live "still running" countdown, since
this call has already returned by the time the report exists.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.research_state import (
    ResearchResultLike,
    ResearchState,
    ResearchStateResult,
    derive_research_state,
)
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.bottleneck_report import (
    ResearchPipelineStage,
    SessionBottleneckReport,
    build_session_bottleneck_report,
)
from knowledge_engine_ai.orchestrator.observability import SessionTrace
from knowledge_engine_ai.orchestrator.session_report import SessionReport, SourcedClaim
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult

RESEARCH_PROGRESS_REPORT_SCHEMA_VERSION = 1


class ResearchProgressStage(StrEnum):
    """Web-facing progress state, matching `knowledge-engine-web#93`'s 8 named states.

    `SEARCHING_INDEXED_EVIDENCE`, `DISCOVERING_SOURCES`, `ACQUIRING_SOURCES`,
    `VALIDATING_EXTRACTING_EVIDENCE`, and `RERETRIEVING` are reserved for a
    future durable/incremental caller; see this module's docstring for why
    the current synchronous derivation never emits them.
    """

    SEARCHING_INDEXED_EVIDENCE = "searching_indexed_evidence"
    RESEARCH_REQUIRED = "research_required"
    DISCOVERING_SOURCES = "discovering_sources"
    ACQUIRING_SOURCES = "acquiring_sources"
    VALIDATING_EXTRACTING_EVIDENCE = "validating_extracting_evidence"
    RERETRIEVING = "reretrieving"
    PARTIAL_ANSWER = "partial_answer"
    FINAL_ANSWER = "final_answer"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


#: The only two stages that satisfy issue #90's "final completion/
#: insufficient-evidence gate" requirement -- everything else means a
#: follow-up call could still add more.
_FINAL_PROGRESS_STAGES = frozenset(
    {ResearchProgressStage.FINAL_ANSWER, ResearchProgressStage.INSUFFICIENT_EVIDENCE}
)


@dataclass(frozen=True)
class ProviderStatusSummary:
    """One federated-discovery provider's attempt outcome, for coverage/degradation display."""

    provider: str
    attempted: bool
    outcome: str | None
    reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "attempted": self.attempted,
            "outcome": self.outcome,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResearchProgressReport:
    """One stable, additive progress/report contract for one research call.

    Every field is derived from facts `run_research_question` already
    recorded -- nothing here is fabricated or estimated. See this module's
    docstring for the full design rationale.
    """

    schema_version: int
    session_id: str
    research_question_id: str | None
    progress_stage: ResearchProgressStage
    current_stage: ResearchPipelineStage
    research_state: ResearchState
    research_state_reason: str
    final: bool
    answer_available: bool
    wait_reason: str | None
    elapsed_ms: int | None
    indexed_evidence_record_ids: tuple[str, ...]
    newly_acquired_evidence_record_ids: tuple[str, ...]
    provider_coverage_attempted: bool
    provider_coverage_completeness: str | None
    provider_degraded: bool
    provider_statuses: tuple[ProviderStatusSummary, ...]
    citations: tuple[SourcedClaim, ...]
    unresolved_citations: tuple[str, ...]
    limitations: tuple[str, ...]
    bottleneck_report: SessionBottleneckReport

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["progress_stage"] = self.progress_stage.value
        payload["current_stage"] = self.current_stage.value
        payload["research_state"] = self.research_state.value
        payload["provider_statuses"] = [status.to_dict() for status in self.provider_statuses]
        payload["bottleneck_report"] = self.bottleneck_report.to_dict()
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class ResearchProgressResultLike(ResearchResultLike, Protocol):
    """`ResearchResultLike` plus the report-closure fields BT-6 additionally needs.

    `ResearchQuestionResult` already satisfies this structurally -- no new
    field was added to that class's public surface to support this Protocol.
    """

    @property
    def session_id(self) -> str: ...

    @property
    def trace(self) -> SessionTrace: ...

    @property
    def session_report(self) -> SessionReport | None: ...

    @property
    def effective_evidence_report(self) -> EvidenceReport | None: ...


def build_research_progress_report(
    result: ResearchProgressResultLike,
    *,
    research_question_id: str | None = None,
) -> ResearchProgressReport:
    """Project one completed `run_research_question` result into a `ResearchProgressReport`.

    Never re-derives adequacy or release eligibility: `research_state.
    derive_research_state` and `bottleneck_report.build_session_bottleneck_report`
    remain the single source of truth for those facts, reused here rather than
    duplicated.
    """

    state = derive_research_state(result)
    bottleneck = build_session_bottleneck_report(result.trace)

    progress_stage = _map_progress_stage(state)
    current_stage = _current_pipeline_stage(state)
    wait_reason = _wait_reason(state)
    final = progress_stage in _FINAL_PROGRESS_STAGES

    newly_acquired_ids = (
        result.grounded_completion.promoted_record_ids
        if result.grounded_completion is not None
        else ()
    )
    provider_attempted, completeness, provider_statuses = _provider_coverage(result.discovery)
    citations, unresolved_citations, limitations = _citations_and_limitations(
        result.session_report, result.effective_evidence_report
    )

    return ResearchProgressReport(
        schema_version=RESEARCH_PROGRESS_REPORT_SCHEMA_VERSION,
        session_id=result.session_id,
        research_question_id=research_question_id,
        progress_stage=progress_stage,
        current_stage=current_stage,
        research_state=state.state,
        research_state_reason=state.reason,
        final=final,
        answer_available=result.narrative_releaseable,
        wait_reason=wait_reason,
        elapsed_ms=bottleneck.adjusted_known_duration_ms,
        indexed_evidence_record_ids=_indexed_evidence_record_ids(result.workflow),
        newly_acquired_evidence_record_ids=newly_acquired_ids,
        provider_coverage_attempted=provider_attempted,
        provider_coverage_completeness=completeness,
        provider_degraded=state.provider_degraded,
        provider_statuses=provider_statuses,
        citations=citations,
        unresolved_citations=unresolved_citations,
        limitations=limitations,
        bottleneck_report=bottleneck,
    )


def _map_progress_stage(state: ResearchStateResult) -> ResearchProgressStage:
    """`ResearchState` -> Web's progress-state vocabulary, never re-judging adequacy.

    `PROVIDER_DEGRADED` is Web's `final_answer` when the releaseable answer
    already used grounded reretrieved evidence, otherwise `partial_answer` --
    the same distinction `ResearchStateResult.used_reretrieved_evidence` and
    `.grounded_completion_completed` already carry, reused rather than
    re-derived from `reason` text.
    """

    if state.state in (ResearchState.INDEXED_ANSWER, ResearchState.RESEARCHED_ANSWER):
        return ResearchProgressStage.FINAL_ANSWER
    if state.state is ResearchState.PARTIAL_ANSWER:
        return ResearchProgressStage.PARTIAL_ANSWER
    if state.state is ResearchState.PROVIDER_DEGRADED:
        if state.used_reretrieved_evidence and state.grounded_completion_completed:
            return ResearchProgressStage.FINAL_ANSWER
        return ResearchProgressStage.PARTIAL_ANSWER
    if state.state in (ResearchState.RESEARCH_REQUIRED, ResearchState.RESEARCHING):
        return ResearchProgressStage.RESEARCH_REQUIRED
    # ResearchState.BLOCKED and ResearchState.INSUFFICIENT_EVIDENCE: fail closed.
    # A blocked required-release-gate is never presented as a final answer,
    # and Web's 8-state vocabulary has no separate "blocked" state -- the
    # underlying `research_state`/`research_state_reason` fields keep the
    # real diagnostic distinction for any caller that needs it.
    return ResearchProgressStage.INSUFFICIENT_EVIDENCE


def _current_pipeline_stage(state: ResearchStateResult) -> ResearchPipelineStage:
    """The fixed-pipeline stage this outcome is anchored to.

    A second *view* of the same deterministic facts `derive_research_state`
    already used to pick a `ResearchState`, expressed as a position in
    `bottleneck_report`'s stable stage taxonomy instead of an outcome label.
    """

    if state.state is ResearchState.BLOCKED:
        return (
            ResearchPipelineStage.INDEXED_RETRIEVAL
            if state.reason == "primary_retrieval_failed"
            else ResearchPipelineStage.REPORT_CLOSE
        )
    if not state.discovery_triggered:
        return ResearchPipelineStage.INDEXED_RETRIEVAL
    if state.used_reretrieved_evidence or (
        state.grounded_completion_attempted and state.grounded_completion_completed
    ):
        return ResearchPipelineStage.RERETRIEVAL
    if state.grounded_completion_attempted:
        return ResearchPipelineStage.EXTRACTION_PROMOTION
    if state.acquisition_plan_attempted:
        return ResearchPipelineStage.ACQUISITION
    if state.federated_discovery_attempted:
        return ResearchPipelineStage.DISCOVERY
    return ResearchPipelineStage.ADEQUACY


def _wait_reason(state: ResearchStateResult) -> str | None:
    """Why a caller would need a follow-up call to get more than this result, or `None`.

    `None` whenever `state.state` already describes a finished outcome
    (a final answer, a post-research `insufficient_evidence`, a releaseable
    partial/degraded answer, or `blocked`) -- nothing further happens to
    *this* call. Only `RESEARCH_REQUIRED` (bounded research was triggered
    but this call's own policy did not carry it through to a grounded
    completion attempt) names a concrete next step, matching the same
    `discovery_triggered`/`federated_discovery_attempted`/
    `acquisition_plan_attempted` facts `research_state.py`'s own reason
    strings already distinguish.
    """

    if state.state is not ResearchState.RESEARCH_REQUIRED:
        return None
    if not state.federated_discovery_attempted and not state.acquisition_plan_attempted:
        return (
            "Indexed coverage was insufficient, but no discovery/acquisition step ran this "
            "call. Supply a FederatedDiscoveryPolicy with acquisition-plan requests enabled "
            "to continue past research_required."
        )
    return (
        "Discovery/acquisition planning ran, but grounded completion was not requested this "
        "call. Supply grounded_completion_policy to continue past research_required toward a "
        "final or insufficient_evidence result."
    )


def _indexed_evidence_record_ids(workflow: WorkflowResult) -> tuple[str, ...]:
    """Every EvidenceRecord ID retrieved from the already-indexed corpus, sorted.

    Mirrors `research_state._indexed_evidence_record_count`'s own union of
    the primary and contradiction-oriented retrieval branches, but keeps the
    identities themselves rather than only their count -- BT-6 needs Web to
    tell indexed evidence apart from newly acquired evidence.
    """

    parallel = workflow.parallel_retrieval
    if parallel is not None:
        return tuple(
            sorted(
                parallel.primary_evidence_record_ids | parallel.contradiction_evidence_record_ids
            )
        )
    report = workflow.evidence_report
    if report is None:
        return ()
    return tuple(
        sorted(
            {
                record.evidence_record_id
                for paper in report.papers
                for record in paper.evidence_records
                if record.evidence_record_id
            }
        )
    )


def _provider_coverage(
    discovery: DiscoveryAugmentationResult | None,
) -> tuple[bool, str | None, tuple[ProviderStatusSummary, ...]]:
    """Returns `(attempted, completeness, provider_statuses)` for coverage/degradation display."""

    if discovery is None:
        return False, None, ()
    if discovery.federated_discovery is None:
        return discovery.federated_discovery_attempted, None, ()
    federated = discovery.federated_discovery
    statuses = tuple(
        ProviderStatusSummary(
            provider=status.provider,
            attempted=status.attempted,
            outcome=status.outcome,
            reason=status.reason,
        )
        for status in federated.provider_statuses
    )
    return True, federated.completeness, statuses


def _citations_and_limitations(
    session_report: SessionReport | None,
    effective_evidence_report: EvidenceReport | None,
) -> tuple[tuple[SourcedClaim, ...], tuple[str, ...], tuple[str, ...]]:
    """Returns `(citations, unresolved_citations, limitations)`.

    `limitations` is the deduplicated, order-preserving union of every
    *cited* EvidenceRecord's own `limitations` field -- never a record the
    narrative did not actually use, and never re-derived from
    `VerificationResult.missed_qualifiers` (which is always empty for a
    releaseable narrative by construction, so it cannot carry this
    information).
    """

    if session_report is None:
        return (), (), ()
    citations = session_report.sourced_claims
    unresolved_citations = session_report.unresolved_citations
    if effective_evidence_report is None or not citations:
        return citations, unresolved_citations, ()

    cited_ids = {claim.evidence_record_id for claim in citations}
    limitations: dict[str, None] = {}
    for paper in effective_evidence_report.papers:
        for record in paper.evidence_records:
            if record.evidence_record_id in cited_ids:
                for limitation in record.limitations:
                    limitations.setdefault(limitation, None)
    return citations, unresolved_citations, tuple(limitations)


__all__ = [
    "RESEARCH_PROGRESS_REPORT_SCHEMA_VERSION",
    "ProviderStatusSummary",
    "ResearchProgressReport",
    "ResearchProgressResultLike",
    "ResearchProgressStage",
    "build_research_progress_report",
]
