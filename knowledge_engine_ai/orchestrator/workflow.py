"""AI-O3: connect existing `core` capabilities to a `ResearchSession` via fixed rules.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O3 success criterion:
"one session can call multiple existing Knowledge Engine capabilities and
assemble structured results without an LLM dynamically deciding
execution." This module is that connection, and nothing more: it does
not plan, does not choose which capability to run based on the
question's content, and does not call an LLM. The step sequence and
each step's run condition are fixed by this module's own code --
retrieval + Evidence Intelligence always run; the evidence-map and
statistical-verification steps run only when the caller supplies their
required curated inputs, an "if configured" branch evaluated once
per call, not a judgment call any executor makes per-question. Real
per-question planning (deciding *which* capabilities a question needs)
is AI-O4's "Local Query Planner" behind this same schema, not this
module's job.

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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine_ai.ke_client import (
    KeCommandError,
    enriched_evidence_report,
    evidence_map_report,
    statistical_verify,
)
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.sessions.models import ResearchEvent
from knowledge_engine_ai.sessions.repository import SessionRepository

_EXECUTOR_TYPE = "deterministic_tool"

_RETRIEVAL_NODE = "retrieval_and_evidence_intelligence"
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
    """The assembled, structured result of one fixed-workflow run."""

    session_id: str
    question: str
    evidence_report: EvidenceReport | None
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
    """

    steps: list[WorkflowStepResult] = []
    report: EvidenceReport | None = None

    try:
        report = enriched_evidence_report(
            question, sources=sources, evidence=evidence, limit=limit, ke_executable=ke_executable
        )
        steps.append(
            _record_step(
                session_repository,
                session_id=session_id,
                workflow_node=_RETRIEVAL_NODE,
                tool_name="ke evidence-report",
                output=_retrieval_summary(report),
                output_hash=_retrieval_output_hash(report),
                output_schema_version=report.schema_version,
                error=None,
            )
        )
    except KeCommandError as exc:
        steps.append(
            _record_step(
                session_repository,
                session_id=session_id,
                workflow_node=_RETRIEVAL_NODE,
                tool_name="ke evidence-report",
                output=None,
                output_hash=None,
                output_schema_version=None,
                error=str(exc),
            )
        )

    if evidence_map is not None and relationships is not None:
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
                )
            )

    if statistical_inputs is not None:
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
                )
            )

    return WorkflowResult(
        session_id=session_id, question=question, evidence_report=report, steps=tuple(steps)
    )


def _retrieval_summary(report: EvidenceReport) -> str:
    """A short, human-readable summary -- the durable audit trail is the event's `output_hash`."""

    evidence_record_ids = sorted(
        record.evidence_record_id
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    )
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
    evidence_record_ids = sorted(
        record.evidence_record_id
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    )
    payload = json.dumps(
        {"paper_ids": paper_ids, "evidence_record_ids": evidence_record_ids}, sort_keys=True
    )
    return _hash(payload)


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
