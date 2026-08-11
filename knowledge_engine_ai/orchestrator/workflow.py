"""AI-O3/AI-O5: connect existing `core` capabilities to a `ResearchSession` via fixed rules.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O3 success criterion:
"one session can call multiple existing Knowledge Engine capabilities and
assemble structured results without an LLM dynamically deciding
execution." This module is that connection, and nothing more: it does
not plan, does not choose which capability to run based on the
question's content, and does not call an LLM. The step sequence and
each step's run condition are fixed by this module's own code --
retrieval (AI-O5: primary and contradiction-oriented, in parallel) plus
Evidence Intelligence always run; the evidence-map and
statistical-verification steps run only when the caller supplies their
required curated inputs, an "if configured" branch evaluated once
per call, not a judgment call any executor makes per-question. Real
per-question planning (deciding *which* capabilities a question needs)
is AI-O4's "Local Query Planner" behind this same schema, not this
module's job.

AI-O5 widened the single "retrieval" step into `orchestrator.parallel_retrieval`'s
`run_parallel_retrieval`: primary retrieval and a second,
contradiction-oriented-worded retrieval run concurrently against the
same corpus, each recorded as its own `ResearchEvent` so a caller (or a
future AI-O6 Skeptic step) can inspect both branches' results
independently, plus the concrete recall-gain signal
(`contradiction_only_evidence_record_ids`) AI-O5's success criterion
asks to measure. `WorkflowResult.evidence_report` still points at the
primary branch's report alone, for backward compatibility with callers
built against AI-O3's single-report shape; `WorkflowResult.parallel_retrieval`
carries the full two-branch detail.

Session lifecycle is the caller's responsibility, matching AI-O2's own
"no implicit chat-order state" discipline: `run_fixed_evidence_workflow`
never calls `SessionRepository.create_session` itself -- the caller
creates (or resumes and re-checks) the session first, then passes its
`session_id` in. This keeps identity/resume decisions where AI-O2 put
them and lets this module stay a pure "run the fixed steps, record what
happened" function.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine_ai.ke_client import (
    KeCommandError,
    evidence_map_report,
    statistical_verify,
)
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    ExternalDiscoveryCallable,
    ParallelRetrievalResult,
    run_parallel_retrieval,
)
from knowledge_engine_ai.sessions.models import ResearchEvent
from knowledge_engine_ai.sessions.repository import SessionRepository

_EXECUTOR_TYPE = "deterministic_tool"

_RETRIEVAL_NODE = "retrieval_and_evidence_intelligence"
_CONTRADICTION_RETRIEVAL_NODE = "contradiction_oriented_retrieval"
_EVIDENCE_MAP_NODE = "evidence_map"
_STATISTICAL_VERIFICATION_NODE = "statistical_verification"


@dataclass(frozen=True)
class WorkflowStepResult:
    """One fixed step's outcome -- always recorded, whether it succeeded or not."""

    workflow_node: str
    tool_name: str
    succeeded: bool
    output: str | None
    error: str | None


@dataclass(frozen=True)
class WorkflowResult:
    """The assembled, structured result of one fixed-workflow run.

    `evidence_report` is the primary retrieval branch's report alone,
    kept for backward compatibility with callers built against AI-O3's
    single-report shape. `parallel_retrieval` (AI-O5) carries the full
    two-branch detail, including the recall-gain signal
    (`contradiction_only_evidence_record_ids`).
    """

    session_id: str
    question: str
    evidence_report: EvidenceReport | None
    parallel_retrieval: ParallelRetrievalResult | None
    steps: tuple[WorkflowStepResult, ...]


def run_fixed_evidence_workflow(
    *,
    session_id: str,
    question: str,
    session_repository: SessionRepository,
    sources: Path,
    evidence: Path,
    limit: int = 5,
    evidence_map: Path | None = None,
    relationships: Path | None = None,
    statistical_inputs: Path | None = None,
    binary_statistical_inputs: Path | None = None,
    external_discovery: ExternalDiscoveryCallable | None = None,
    ke_executable: str = "ke",
) -> WorkflowResult:
    """Run the fixed step sequence against an already-created `session_id`.

    Every step appends exactly one `ResearchEvent` to `session_id`,
    whether it succeeds or raises `KeCommandError` -- a failed step is
    still durable workflow history (AI-O2's whole point), not a step
    that silently vanishes. One step's failure does not stop the
    remaining fixed steps from being attempted; `WorkflowResult.steps`
    reports every outcome so a caller can see exactly what happened
    without re-deriving it from the event log.

    AI-O5: retrieval runs primary and contradiction-oriented queries
    concurrently (`orchestrator.parallel_retrieval.run_parallel_retrieval`),
    always, the same "always run" status the single retrieval step had
    under AI-O3 -- not gated behind an "if configured" branch the way
    the evidence-map/statistical-verification steps below are, since
    AI-O5's milestone text names this "in parallel" with primary
    retrieval, not conditional on it. Each branch is recorded as its own
    `ResearchEvent`.
    """

    steps: list[WorkflowStepResult] = []
    report: EvidenceReport | None = None
    parallel_result: ParallelRetrievalResult | None = None

    retrieval_start = time.monotonic()
    parallel_result = run_parallel_retrieval(
        question,
        sources=sources,
        evidence=evidence,
        limit=limit,
        external_discovery=external_discovery,
        ke_executable=ke_executable,
    )
    # Both branches run concurrently inside `run_parallel_retrieval`'s own
    # thread pool, so this is the combined call's wall-clock time, not an
    # isolated per-branch cost -- both retrieval events below get the same
    # duration_ms for that reason (see docs/ai_o9_design.md).
    retrieval_duration_ms = _elapsed_ms(retrieval_start)
    report = parallel_result.primary.report
    steps.append(
        _record_step(
            session_repository,
            session_id=session_id,
            workflow_node=_RETRIEVAL_NODE,
            tool_name="ke evidence-report",
            output=_retrieval_summary(report) if report is not None else None,
            output_hash=_retrieval_output_hash(report) if report is not None else None,
            output_schema_version=report.schema_version if report is not None else None,
            error=parallel_result.primary.error,
            duration_ms=retrieval_duration_ms,
            source_ids=_evidence_record_ids(report) if report is not None else (),
        )
    )
    contradiction_report = parallel_result.contradiction.report
    steps.append(
        _record_step(
            session_repository,
            session_id=session_id,
            workflow_node=_CONTRADICTION_RETRIEVAL_NODE,
            tool_name="ke evidence-report (contradiction-oriented)",
            output=(
                _retrieval_summary(contradiction_report)
                if contradiction_report is not None
                else None
            ),
            output_hash=(
                _retrieval_output_hash(contradiction_report)
                if contradiction_report is not None
                else None
            ),
            output_schema_version=(
                contradiction_report.schema_version if contradiction_report is not None else None
            ),
            error=parallel_result.contradiction.error,
            duration_ms=retrieval_duration_ms,
            source_ids=(
                _evidence_record_ids(contradiction_report)
                if contradiction_report is not None
                else ()
            ),
        )
    )

    if evidence_map is not None and relationships is not None:
        evidence_map_start = time.monotonic()
        try:
            map_report = evidence_map_report(
                evidence_map,
                evidence=evidence,
                relationships=relationships,
                sources=sources,
                ke_executable=ke_executable,
            )
            steps.append(
                _record_step(
                    session_repository,
                    session_id=session_id,
                    workflow_node=_EVIDENCE_MAP_NODE,
                    tool_name="ke evidence-map-report",
                    output=map_report,
                    output_hash=_hash(map_report),
                    output_schema_version=None,
                    error=None,
                    duration_ms=_elapsed_ms(evidence_map_start),
                )
            )
        except KeCommandError as exc:
            steps.append(
                _record_step(
                    session_repository,
                    session_id=session_id,
                    workflow_node=_EVIDENCE_MAP_NODE,
                    tool_name="ke evidence-map-report",
                    output=None,
                    output_hash=None,
                    output_schema_version=None,
                    error=str(exc),
                    duration_ms=_elapsed_ms(evidence_map_start),
                )
            )

    if statistical_inputs is not None:
        statistical_verification_start = time.monotonic()
        try:
            stats_report = statistical_verify(
                statistical_inputs,
                evidence=evidence,
                binary_inputs=binary_statistical_inputs,
                ke_executable=ke_executable,
            )
            steps.append(
                _record_step(
                    session_repository,
                    session_id=session_id,
                    workflow_node=_STATISTICAL_VERIFICATION_NODE,
                    tool_name="ke statistical-verify",
                    output=stats_report,
                    output_hash=_hash(stats_report),
                    output_schema_version=None,
                    error=None,
                    duration_ms=_elapsed_ms(statistical_verification_start),
                )
            )
        except KeCommandError as exc:
            steps.append(
                _record_step(
                    session_repository,
                    session_id=session_id,
                    workflow_node=_STATISTICAL_VERIFICATION_NODE,
                    tool_name="ke statistical-verify",
                    output=None,
                    output_hash=None,
                    output_schema_version=None,
                    error=str(exc),
                    duration_ms=_elapsed_ms(statistical_verification_start),
                )
            )

    return WorkflowResult(
        session_id=session_id,
        question=question,
        evidence_report=report,
        parallel_retrieval=parallel_result,
        steps=tuple(steps),
    )


def _evidence_record_ids(report: EvidenceReport) -> tuple[str, ...]:
    """Every retrieved evidence-record identity in `report`, sorted for determinism."""

    return tuple(
        sorted(
            record.evidence_record_id
            for paper in report.papers
            for record in paper.evidence_records
            if record.evidence_record_id
        )
    )


def _retrieval_summary(report: EvidenceReport) -> str:
    """A short, human-readable summary -- the durable audit trail is the event's `output_hash`."""

    evidence_record_ids = _evidence_record_ids(report)
    return (
        f"{len(report.papers)} paper(s), {len(evidence_record_ids)} evidence record(s) retrieved."
    )


def _retrieval_output_hash(report: EvidenceReport) -> str:
    """Hash the retrieved paper/evidence-record identities, not float retrieval scores.

    Deterministic across re-runs of the same corpus snapshot for the
    same question -- two runs that retrieved the same records should
    hash identically, which a score-inclusive hash could break on
    floating-point noise.
    """

    paper_ids = [paper.paper_id for paper in report.papers]
    payload = json.dumps(
        {"paper_ids": paper_ids, "evidence_record_ids": list(_evidence_record_ids(report))},
        sort_keys=True,
    )
    return _hash(payload)


def _elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _record_step(
    session_repository: SessionRepository,
    *,
    session_id: str,
    workflow_node: str,
    tool_name: str,
    output: str | None,
    output_hash: str | None,
    output_schema_version: int | None,
    error: str | None,
    duration_ms: int | None = None,
    source_ids: tuple[str, ...] = (),
) -> WorkflowStepResult:
    event = ResearchEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        workflow_node=workflow_node,
        executor_type=_EXECUTOR_TYPE,
        validation_status="succeeded" if error is None else "failed",
        output_schema_version=output_schema_version,
        output_hash=output_hash,
        tool_name=tool_name,
        notes=error,
        duration_ms=duration_ms,
        source_ids=source_ids,
    )
    session_repository.append_event(event)
    return WorkflowStepResult(
        workflow_node=workflow_node,
        tool_name=tool_name,
        succeeded=error is None,
        output=output,
        error=error,
    )


def _hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
