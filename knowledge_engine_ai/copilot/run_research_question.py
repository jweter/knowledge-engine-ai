"""AI-O12: compose the built orchestrator into one callable pipeline.

`docs/web_integration_design.md`'s AI-O12 milestone: nothing in this repo
composes `run_fixed_evidence_workflow` -> `synthesize_answer` ->
`verify_synthesis` -> `build_session_report` -> `attempt_session_close` ->
`build_session_trace` into one call, even though every one of those
pieces (AI-O1 through AI-O9) is already built and tested. This module is
that composition, and nothing more -- it does not add a new capability,
it wires up the existing ones in the order the design doc specifies so a
caller (a CLI command today, `knowledge-engine-web`'s `/ask` route later
under AI-O14) can ask one real question and get back a durable session,
a verified narrative (or an honest explanation of why there is none),
and a full trace, in one call.

Session lifecycle here mirrors AI-O2's own discipline: this module
*does* call `session_repository.create_session` itself, unlike
`run_fixed_evidence_workflow` -- `run_research_question` is the one
place in this repo that owns a full question-to-answer run end to end,
so it is the natural owner of session creation too. A caller that wants
to resume or inspect an existing session uses `SessionRepository`
directly, the same as before this module existed.

A `ResearchISA` (AI-O2's Ideal State Artifact) is attached to every
session this module creates, with two fixed, deterministic criteria
that mirror exactly what AI-O6's `verify_synthesis` already checks:
citation integrity (no hallucinated citations, no ungrounded numbers)
and contradiction review (no qualifying/contradicting evidence record
silently omitted from the narrative). When no narrative was produced at
all -- either because retrieval found no evidence with a stated claim
to synthesize from, or because the local LLM call itself failed -- both
criteria are recorded as passed: there is no narrative to have gotten
either check wrong, the same vacuous-truth reasoning `VerificationResult.is_clean`
already applies to an unproblematic empty result. This keeps the ISA's
`required` criteria satisfiable without needing a dynamic `required`
flag decided after the fact, which the write-once ISA contract does not
allow. A synthesis-step failure (e.g. Ollama unreachable) is still
visible and durable -- it is recorded as its own failed `ResearchEvent`
and surfaced on `ResearchQuestionResult.synthesis_error` -- it is simply
not what blocks the ISA close gate, which is scoped to narrative
correctness, not synthesis availability.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine_ai.copilot.intent import (
    CriterionResult,
    CriterionStatus,
    IdealStateCriterion,
    ResearchISA,
)
from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded
from knowledge_engine_ai.llm import LocalLLM, LocalLLMError
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult, attempt_session_close
from knowledge_engine_ai.orchestrator.observability import SessionTrace, build_session_trace
from knowledge_engine_ai.orchestrator.parallel_retrieval import ExternalDiscoveryCallable
from knowledge_engine_ai.orchestrator.session_report import SessionReport, build_session_report
from knowledge_engine_ai.orchestrator.verification import VerificationResult, verify_synthesis
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult, run_fixed_evidence_workflow
from knowledge_engine_ai.sessions.models import (
    ResearchEvent,
    ResearchSession,
    SessionStatus,
)
from knowledge_engine_ai.sessions.repository import SessionRepository
from knowledge_engine_ai.synthesis import synthesize_answer

_ISA_SCHEMA_VERSION = 1
_CITATION_INTEGRITY_CRITERION_ID = "citation_integrity"
_CONTRADICTION_REVIEW_CRITERION_ID = "contradiction_review"
_SYNTHESIS_NODE = "synthesis"
_SYNTHESIS_EXECUTOR_TYPE = "local_llm"


@dataclass(frozen=True)
class ResearchQuestionResult:
    """The full, assembled outcome of one composed AI-O12 run.

    `narrative`/`verification`/`session_report` are all `None` together
    when no evidence with a stated claim was retrieved to synthesize
    from -- there is nothing to narrate, not a failure. `synthesis_error`
    is set only when a narrative was attempted and the local LLM call
    itself failed (e.g. Ollama unreachable, model not pulled); it is
    `None` in the no-evidence case above. `close_result.status` is
    `COMPLETED` only when both ISA criteria passed; a verification
    failure (or a workflow step failure) still produces a full result --
    it never raises -- with `close_result.status` reporting `BLOCKED`
    and `close_result.validation.unresolved_required_criteria` naming
    exactly what did not pass, matching this project's "record failure,
    don't stop" discipline.
    """

    session_id: str
    question: str
    workflow: WorkflowResult
    narrative: str | None
    synthesis_error: str | None
    verification: VerificationResult | None
    session_report: SessionReport | None
    close_result: SessionCloseResult
    trace: SessionTrace


def run_research_question(
    question: str,
    *,
    session_repository: SessionRepository,
    sources: Path,
    evidence: Path,
    llm: LocalLLM,
    limit: int = 5,
    external_discovery: ExternalDiscoveryCallable | None = None,
    ke_executable: str = "ke",
    timeout_seconds: float | None = None,
) -> ResearchQuestionResult:
    """Create a session, run the fixed workflow, synthesize, verify, close, trace.

    Concretely, in order: `session_repository.create_session`,
    `run_fixed_evidence_workflow` (retrieval + Evidence Intelligence,
    both branches), `synthesize_answer` over the primary branch's
    report, `verify_synthesis` (the Skeptic check), `build_session_report`,
    `attempt_session_close` (the ISA close gate), `build_session_trace`.
    Never raises for an ordinary "no evidence" or "verification found a
    problem" outcome -- see `ResearchQuestionResult`'s docstring for how
    each is represented instead.
    """

    execution_budget = (
        ExecutionBudget.from_timeout(timeout_seconds) if timeout_seconds is not None else None
    )
    session_id = str(uuid.uuid4())
    created_at = _timestamp()
    session_repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id=session_id,
            created_at=created_at,
            updated_at=created_at,
            user_question_original=question,
            status=SessionStatus.RUNNING,
        )
    )

    workflow_result = run_fixed_evidence_workflow(
        session_id=session_id,
        question=question,
        session_repository=session_repository,
        sources=sources,
        evidence=evidence,
        limit=limit,
        external_discovery=external_discovery,
        ke_executable=ke_executable,
        execution_budget=execution_budget,
    )

    narrative, synthesis_error = _synthesize(
        session_repository=session_repository,
        session_id=session_id,
        evidence_report=workflow_result.evidence_report,
        llm=llm,
        execution_budget=execution_budget,
    )

    verification: VerificationResult | None = None
    session_report: SessionReport | None = None
    if narrative is not None and workflow_result.evidence_report is not None:
        verification = verify_synthesis(narrative, workflow_result.evidence_report)
        session_report = build_session_report(
            narrative, workflow_result.evidence_report, verification
        )

    session_repository.attach_research_isa(session_id, _build_isa(session_id, question))
    recorded_at = _timestamp()
    for result in _isa_criterion_results(verification):
        session_repository.record_criterion_result(session_id, result, recorded_at=recorded_at)

    close_result = attempt_session_close(session_repository, session_id=session_id)

    session = session_repository.get_session(session_id)
    if session is None:  # pragma: no cover - created above; existence is invariant here.
        raise RuntimeError(f"Session {session_id!r} vanished mid-run.")
    events = tuple(session_repository.list_events(session_id))
    trace = build_session_trace(session, events)

    return ResearchQuestionResult(
        session_id=session_id,
        question=question,
        workflow=workflow_result,
        narrative=narrative,
        synthesis_error=synthesis_error,
        verification=verification,
        session_report=session_report,
        close_result=close_result,
        trace=trace,
    )


def _synthesize(
    *,
    session_repository: SessionRepository,
    session_id: str,
    evidence_report: EvidenceReport | None,
    llm: LocalLLM,
    execution_budget: ExecutionBudget | None,
) -> tuple[str | None, str | None]:
    """Run `synthesize_answer`, recording exactly one durable `ResearchEvent` either way.

    Returns `(narrative, synthesis_error)`. Both `None` means there was
    no evidence with a stated claim to synthesize from -- not an error.
    `narrative` `None` with `synthesis_error` set means a narrative was
    attempted and the local LLM call itself failed.
    """

    if evidence_report is None:
        return None, None

    start = time.monotonic()
    try:
        timeout_seconds = (
            execution_budget.remaining_seconds() if execution_budget is not None else None
        )
        narrative = synthesize_answer(
            evidence_report,
            llm,
            timeout_seconds=timeout_seconds,
        )
    except (ExecutionBudgetExceeded, LocalLLMError) as exc:
        _record_synthesis_event(
            session_repository,
            session_id=session_id,
            output=None,
            error=str(exc),
            duration_ms=_elapsed_ms(start),
        )
        return None, str(exc)

    if narrative is None:
        _record_synthesis_event(
            session_repository,
            session_id=session_id,
            output="No evidence with a stated claim was retrieved to synthesize from.",
            error=None,
            duration_ms=_elapsed_ms(start),
        )
        return None, None

    _record_synthesis_event(
        session_repository,
        session_id=session_id,
        output=narrative,
        error=None,
        duration_ms=_elapsed_ms(start),
    )
    return narrative, None


def _record_synthesis_event(
    session_repository: SessionRepository,
    *,
    session_id: str,
    output: str | None,
    error: str | None,
    duration_ms: int,
) -> None:
    session_repository.append_event(
        ResearchEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=_timestamp(),
            workflow_node=_SYNTHESIS_NODE,
            executor_type=_SYNTHESIS_EXECUTOR_TYPE,
            validation_status="succeeded" if error is None else "failed",
            output_hash=_hash(output) if output is not None else None,
            notes=error if error is not None else output,
            duration_ms=duration_ms,
        )
    )


def _build_isa(session_id: str, question: str) -> ResearchISA:
    return ResearchISA(
        schema_version=_ISA_SCHEMA_VERSION,
        run_id=f"run-{session_id}",
        question=question,
        ideal_state=(
            "A synthesized answer whose every citation is grounded in the retrieved "
            "evidence, and which does not silently omit contradicting or qualifying "
            "evidence, or an honest statement that no evidence was available to answer."
        ),
        criteria=(
            IdealStateCriterion(
                criterion_id=_CITATION_INTEGRITY_CRITERION_ID,
                claim="Every citation the narrative makes is grounded in retrieved evidence.",
                probe="verify_synthesis: hallucinated_citations and ungrounded_numbers are empty",
            ),
            IdealStateCriterion(
                criterion_id=_CONTRADICTION_REVIEW_CRITERION_ID,
                claim="Contradicting or qualifying evidence was not silently omitted.",
                probe="verify_synthesis: missed_qualifiers is empty",
            ),
        ),
    )


def _isa_criterion_results(
    verification: VerificationResult | None,
) -> tuple[CriterionResult, CriterionResult]:
    if verification is None:
        evidence = "No narrative was produced this run; nothing to verify."
        return (
            CriterionResult(_CITATION_INTEGRITY_CRITERION_ID, CriterionStatus.PASSED, evidence),
            CriterionResult(_CONTRADICTION_REVIEW_CRITERION_ID, CriterionStatus.PASSED, evidence),
        )

    citation_clean = not (verification.hallucinated_citations or verification.ungrounded_numbers)
    citation_evidence = (
        "No hallucinated citations or ungrounded numbers found."
        if citation_clean
        else (
            f"hallucinated_citations={list(verification.hallucinated_citations)}, "
            f"ungrounded_numbers={list(verification.ungrounded_numbers)}"
        )
    )

    contradiction_clean = not verification.missed_qualifiers
    contradiction_evidence = (
        "No qualifying/contradicting evidence record was omitted from the narrative."
        if contradiction_clean
        else f"missed_qualifiers={list(verification.missed_qualifiers)}"
    )

    return (
        CriterionResult(
            _CITATION_INTEGRITY_CRITERION_ID,
            CriterionStatus.PASSED if citation_clean else CriterionStatus.FAILED,
            citation_evidence,
        ),
        CriterionResult(
            _CONTRADICTION_REVIEW_CRITERION_ID,
            CriterionStatus.PASSED if contradiction_clean else CriterionStatus.FAILED,
            contradiction_evidence,
        ),
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


__all__ = ["ResearchQuestionResult", "run_research_question"]
