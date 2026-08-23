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

AI-FRD-3/AI-FRD-4 wiring (`copilot/discovery_policy.py`): when a caller
supplies `discovery_policy`, this module evaluates a deterministic
coverage-gap trigger right after the fixed retrieval workflow runs and,
if it fires, compiles/executes a bounded `DiscoveryPlan` (AI-FRD-3) and a
bounded citation-snowball expansion (AI-FRD-4) seeded from the corpus's
own already-relevant papers. `discovery_policy` defaults to `None`,
which reproduces this function's pre-AI-FRD-3/4-wiring behavior exactly
-- no new subprocess call, no new cost -- matching
`docs/agent-development-policy.md` section 2's cost-consciousness rule
for optional-capability opt-in. See `discovery_policy.py`'s own
docstring for the full trigger/budget/provenance policy.

A `ResearchISA` (AI-O2's Ideal State Artifact) is attached to every
session this module creates, with three fixed, deterministic criteria:
workflow integrity (every required deterministic step succeeded), citation
integrity (no hallucinated citations or ungrounded numbers), and contradiction
review (no qualifying/contradicting evidence record silently omitted from the
narrative). When no narrative was produced at
all -- either because retrieval found no evidence with a stated claim
to synthesize from, or because the local LLM call itself failed -- both
two narrative criteria are recorded as passed: there is no narrative to have
gotten either check wrong, the same vacuous-truth reasoning
`VerificationResult.is_clean` already applies to an unproblematic empty result.
The independent workflow-integrity criterion still blocks a failed retrieval.
This keeps the ISA's
`required` criteria satisfiable without needing a dynamic `required`
flag decided after the fact, which the write-once ISA contract does not
allow. A synthesis-step failure (e.g. Ollama unreachable) is still
visible and durable -- it is recorded as its own failed `ResearchEvent`
and surfaced on `ResearchQuestionResult.synthesis_error` -- it is simply
not what blocks the ISA close gate, which is scoped to narrative
correctness, not synthesis availability.

AI-FRD-2's first bounded slice (coverage-aware Research ISA): when a caller
supplies `discovery_policy`, a fourth, *optional* (`required=False`)
`discovery_coverage` criterion is attached alongside the three fixed ones
above and evaluated from the same `DiscoveryAugmentationResult` AI-FRD-3/
AI-FRD-4's wiring already produces. It reports `FAILED` -- naming the
specific provider(s) and their recorded outcome -- whenever a triggered
federated-discovery run's own Core-derived `completeness` is not
`"complete"` (i.e. some attempted provider genuinely failed, was rate
limited, or was unavailable; Core's own `completeness` already excludes
disabled/skipped providers from this judgment, so AI never re-derives it).
It is `NOT_APPLICABLE` when discovery was not triggered (coverage was
already sufficient, or the primary retrieval itself failed and is already
blocked by `workflow_integrity`), or when it was triggered but federated
discovery is disabled by policy (never attempted, so there is no provider
outcome to judge), and omitted from the ISA entirely when no
`discovery_policy` was supplied at all -- the existing three-criteria path
is unchanged byte for byte. Being optional means a degraded federated
search never silently blocks session close (synthesis may still proceed in
degraded mode), but it also means the limitation is always explicit and
inspectable on the session's own ISA validation, never hidden behind a
model's unverified claim to have "searched broadly." See
`docs/roadmap/federated_discovery_orchestration_adoption.md`'s AI-FRD-2
section.

`research_question_id` threading (`docs/roadmap/answer_session_versioning_design.md`):
this module now accepts an optional `research_question_id` and always sets
it on the `ResearchSession` it creates (caller-supplied, or deterministically
derived from the question text when omitted), forwarding it to the
federated-discovery sub-step only when `discovery_policy` is also supplied.
This closes the concrete plumbing gap that design doc's "Where
`research_question_id` actually comes from" section named -- Core's
`federated_discover_history`/`federated_coverage_report` now have something
to find later for any session whose discovery step actually ran under a
given thread identity.

`answer_version`/`supersedes_session_id` threading (2026-08-22, later still):
this module also now accepts optional `answer_version` (default `1`) and
`supersedes_session_id` (default `None`) keyword parameters, set verbatim
on the `ResearchSession` it creates -- additive, same opt-in shape as
`research_question_id` itself, so every existing caller that does not pass
them keeps today's behavior (`answer_version=1`, `supersedes_session_id=None`)
exactly. This module still never calls `SessionRepository.supersede_session`
itself -- minting version *N+1* and superseding version *N* once *N+1*
reaches `COMPLETED` is `copilot.research_freshness.mint_next_version`'s job
(see that module), which calls this function as its own version-*N+1*
sub-step rather than duplicating the session-creation/workflow/synthesis/
close-gate composition here. `narrative_invalidated_at` and the crosswalk/
rerun-trigger wiring the design doc also scopes remain, as before, owned by
`copilot.research_freshness`.

Issue #69 Stage 4 (candidate triage and acquisition): `discovery_policy.py`
now also decides *when* to request a bounded Core acquisition plan for a
triggered federated-discovery run's own candidates
(`FederatedDiscoveryPolicy.enable_acquisition_plan`, default `False` --
see that module's own docstring). This module does not call the
acquisition-plan wrapper directly; it surfaces the outcome unchanged on
`ResearchQuestionResult.discovery.acquisition_plan` alongside the existing
`federated_discovery`/`citation_snowball` fields, the same way it already
surfaces every other `DiscoveryAugmentationResult` field.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine_ai.copilot.discovery_policy import (
    DiscoveryAugmentationResult,
    FederatedDiscoveryPolicy,
    evaluate_and_run_discovery_augmentation,
)
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
_WORKFLOW_INTEGRITY_CRITERION_ID = "workflow_integrity"
_CITATION_INTEGRITY_CRITERION_ID = "citation_integrity"
_CONTRADICTION_REVIEW_CRITERION_ID = "contradiction_review"
_DISCOVERY_COVERAGE_CRITERION_ID = "discovery_coverage"
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
    `COMPLETED` only when all three ISA criteria passed; a verification
    failure (or a workflow step failure) still produces a full result --
    it never raises -- with `close_result.status` reporting `BLOCKED`
    and `close_result.validation.unresolved_required_criteria` naming
    exactly what did not pass, matching this project's "record failure,
    don't stop" discipline. `discovery` is `None` whenever the caller did
    not supply a `discovery_policy` (the default, reproducing this
    module's pre-AI-FRD-3/4-wiring behavior exactly); otherwise it always
    carries a `DiscoveryAugmentationResult` recording the coverage-gap
    trigger decision that was made, even when the trigger did not fire --
    never silently absent once a policy is in effect.
    """

    session_id: str
    question: str
    workflow: WorkflowResult
    discovery: DiscoveryAugmentationResult | None
    narrative: str | None
    synthesis_error: str | None
    verification: VerificationResult | None
    session_report: SessionReport | None
    close_result: SessionCloseResult
    trace: SessionTrace

    @property
    def narrative_releaseable(self) -> bool:
        """Whether the draft narrative passed every deterministic release gate."""

        return (
            self.narrative is not None
            and self.verification is not None
            and self.verification.is_clean
            and self.close_result.status is SessionStatus.COMPLETED
        )


def run_research_question(
    question: str,
    *,
    session_repository: SessionRepository,
    sources: Path,
    evidence: Path,
    llm: LocalLLM,
    limit: int = 5,
    external_discovery: ExternalDiscoveryCallable | None = None,
    discovery_policy: FederatedDiscoveryPolicy | None = None,
    research_question_id: str | None = None,
    answer_version: int = 1,
    supersedes_session_id: str | None = None,
    ke_executable: str = "ke",
    timeout_seconds: float | None = None,
) -> ResearchQuestionResult:
    """Create a session, run the fixed workflow, synthesize, verify, close, trace.

    Concretely, in order: `session_repository.create_session`,
    `run_fixed_evidence_workflow` (retrieval + Evidence Intelligence,
    both branches), the AI-FRD-3/AI-FRD-4 coverage-gap discovery policy
    (only when `discovery_policy` is supplied -- see `discovery_policy.py`),
    `synthesize_answer` over the primary branch's report, `verify_synthesis`
    (the Skeptic check), `build_session_report`, `attempt_session_close`
    (the ISA close gate), `build_session_trace`. Never raises for an
    ordinary "no evidence" or "verification found a problem" outcome --
    see `ResearchQuestionResult`'s docstring for how each is represented
    instead. The discovery policy step never raises either -- see
    `evaluate_and_run_discovery_augmentation`'s own docstring.

    `research_question_id` is the answer/session-versioning thread identity
    `docs/roadmap/answer_session_versioning_design.md` scopes: the same
    string `ke_client.federated_discover()`/`federated_discover_history()`
    key on, so a later freshness check can find every federated-discovery
    run tagged under this question's thread. When a caller supplies one, it
    is used verbatim -- typically a stable per-question-thread identifier a
    caller mints and persists on its own side. When omitted (the common
    case today, until such a caller exists), one is derived deterministically
    from the normalized question text, so separate calls that are really
    "the same question, asked again" thread together even without a caller
    coordinating an ID -- a named trade-off, not a guarantee of uniqueness
    in a multi-tenant setting (see the design doc's "Origin" section). Always
    set on the created `ResearchSession`, and forwarded to the discovery
    step only when `discovery_policy` is also supplied.

    `answer_version`/`supersedes_session_id` are the remaining two
    answer/session-versioning fields: additive, default to `1`/`None` (a
    thread's first version, replacing nothing), and set verbatim on the
    created `ResearchSession` -- this function does no version-numbering or
    thread-lookup logic itself. A caller minting version *N+1* (typically
    `copilot.research_freshness.mint_next_version`, not a person calling
    this function directly) supplies the prior version's
    `answer_version + 1` and its `session_id`.
    """

    execution_budget = (
        ExecutionBudget.from_timeout(timeout_seconds) if timeout_seconds is not None else None
    )
    session_id = str(uuid.uuid4())
    resolved_research_question_id = research_question_id or _derive_research_question_id(question)
    created_at = _timestamp()
    session_repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id=session_id,
            created_at=created_at,
            updated_at=created_at,
            user_question_original=question,
            status=SessionStatus.RUNNING,
            research_question_id=resolved_research_question_id,
            answer_version=answer_version,
            supersedes_session_id=supersedes_session_id,
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

    discovery_augmentation: DiscoveryAugmentationResult | None = None
    if discovery_policy is not None:
        discovery_augmentation = evaluate_and_run_discovery_augmentation(
            session_repository=session_repository,
            session_id=session_id,
            workflow_result=workflow_result,
            policy=discovery_policy,
            execution_budget=execution_budget,
            research_question_id=resolved_research_question_id,
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

    session_repository.attach_research_isa(
        session_id,
        _build_isa(session_id, question, discovery_policy_supplied=discovery_policy is not None),
    )
    recorded_at = _timestamp()
    for result in _isa_criterion_results(workflow_result, verification, discovery_augmentation):
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
        discovery=discovery_augmentation,
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


def _build_isa(session_id: str, question: str, *, discovery_policy_supplied: bool) -> ResearchISA:
    criteria: tuple[IdealStateCriterion, ...] = (
        IdealStateCriterion(
            criterion_id=_WORKFLOW_INTEGRITY_CRITERION_ID,
            claim="Every required deterministic workflow step completed successfully.",
            probe="workflow_result: every configured step has succeeded=true",
        ),
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
    )
    if discovery_policy_supplied:
        # AI-FRD-2: optional (`required=False`) -- a degraded federated-discovery
        # broadening must never silently block session close, but it must also
        # never be silently omitted from the ISA once discovery is in play.
        criteria = (
            *criteria,
            IdealStateCriterion(
                criterion_id=_DISCOVERY_COVERAGE_CRITERION_ID,
                claim=(
                    "If federated discovery was triggered to broaden thin corpus "
                    "coverage, every attempted provider succeeded; a genuine provider "
                    "failure is reported explicitly, never silently as complete coverage."
                ),
                probe="discovery_augmentation: federated_discovery.completeness == 'complete'",
                required=False,
            ),
        )
    return ResearchISA(
        schema_version=_ISA_SCHEMA_VERSION,
        run_id=f"run-{session_id}",
        question=question,
        ideal_state=(
            "A synthesized answer whose every citation is grounded in the retrieved "
            "evidence, and which does not silently omit contradicting or qualifying "
            "evidence, or an honest statement that no evidence was available to answer."
        ),
        criteria=criteria,
    )


def _isa_criterion_results(
    workflow_result: WorkflowResult,
    verification: VerificationResult | None,
    discovery_augmentation: DiscoveryAugmentationResult | None,
) -> tuple[CriterionResult, ...]:
    failed_workflow_nodes = tuple(
        step.workflow_node for step in workflow_result.steps if not step.succeeded
    )
    workflow_clean = not failed_workflow_nodes
    workflow_result_record = CriterionResult(
        _WORKFLOW_INTEGRITY_CRITERION_ID,
        CriterionStatus.PASSED if workflow_clean else CriterionStatus.FAILED,
        (
            "Every required deterministic workflow step succeeded."
            if workflow_clean
            else f"failed_workflow_nodes={list(failed_workflow_nodes)}"
        ),
    )

    if verification is None:
        evidence = "No narrative was produced this run; nothing to verify."
        results = (
            workflow_result_record,
            CriterionResult(_CITATION_INTEGRITY_CRITERION_ID, CriterionStatus.PASSED, evidence),
            CriterionResult(_CONTRADICTION_REVIEW_CRITERION_ID, CriterionStatus.PASSED, evidence),
        )
    else:
        citation_clean = not (
            verification.hallucinated_citations or verification.ungrounded_numbers
        )
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

        results = (
            workflow_result_record,
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

    if discovery_augmentation is None:
        return results
    return (*results, _discovery_coverage_result(discovery_augmentation))


def _discovery_coverage_result(
    discovery_augmentation: DiscoveryAugmentationResult,
) -> CriterionResult:
    """AI-FRD-2: deterministic coverage criterion over this run's discovery augmentation.

    Never re-derives provider success/failure -- Core's own `completeness`
    (already computed only from *attempted* providers, excluding disabled/
    skipped ones) is the single source of truth. `NOT_APPLICABLE` when
    discovery was not triggered at all (coverage was already sufficient, or
    primary retrieval failed and is already blocked by `workflow_integrity`),
    so this criterion never fabricates a "searched broadly" pass for a run
    that never broadened its search.
    """

    if not discovery_augmentation.triggered:
        return CriterionResult(
            _DISCOVERY_COVERAGE_CRITERION_ID,
            CriterionStatus.NOT_APPLICABLE,
            discovery_augmentation.trigger_reason,
        )

    if not discovery_augmentation.federated_discovery_attempted:
        return CriterionResult(
            _DISCOVERY_COVERAGE_CRITERION_ID,
            CriterionStatus.NOT_APPLICABLE,
            (
                "Federated discovery is disabled by policy; this run's coverage gap "
                "was not addressed via federated providers."
            ),
        )

    federated_result = discovery_augmentation.federated_discovery
    if federated_result is None:
        return CriterionResult(
            _DISCOVERY_COVERAGE_CRITERION_ID,
            CriterionStatus.FAILED,
            (
                "Federated discovery was triggered but did not complete: "
                f"{discovery_augmentation.federated_discovery_error}"
            ),
        )

    if federated_result.completeness == "complete":
        return CriterionResult(
            _DISCOVERY_COVERAGE_CRITERION_ID,
            CriterionStatus.PASSED,
            f"Every attempted provider succeeded (search_run_id={federated_result.search_run_id}).",
        )

    unsuccessful = tuple(
        f"{status.provider}={status.outcome}" + (f" ({status.reason})" if status.reason else "")
        for status in federated_result.provider_statuses
        if status.attempted and status.outcome not in ("success", "empty")
    )
    return CriterionResult(
        _DISCOVERY_COVERAGE_CRITERION_ID,
        CriterionStatus.FAILED,
        (
            f"Federated discovery completeness={federated_result.completeness} "
            f"(search_run_id={federated_result.search_run_id}); "
            f"unsuccessful attempted providers: {list(unsuccessful)}"
        ),
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _derive_research_question_id(question: str) -> str:
    """Deterministically derive a thread identity from question text alone.

    A different prefix/truncation than `_hash`'s own `sha256:` output,
    since this is a thread identity meant to be reused across separate
    calls asking "the same question," not a tamper-evidence value for one
    call's own output. Deliberately not a fresh `uuid4()` -- see
    `docs/roadmap/answer_session_versioning_design.md`'s "Origin" section
    for why derivation from the question text, not randomness, is the
    right default here, and the named trade-off that comes with it.
    """

    normalized = question.strip().lower()
    return f"rq-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


__all__ = ["ResearchQuestionResult", "run_research_question"]
