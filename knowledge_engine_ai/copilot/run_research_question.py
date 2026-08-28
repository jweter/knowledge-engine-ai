"""Compose one durable research session from retrieval through grounded synthesis.

The default path remains the original AI-O12 workflow: fixed corpus retrieval,
optional discovery augmentation, synthesis, deterministic verification, ISA close,
and trace construction. When a caller also supplies ``grounded_completion_policy``,
the same session continues through GQR-4/GQR-5 after discovery: eligible papers are
acquired/reused, extracted into privately staged evidence, grounding-verified,
promoted, and the researcher's original question is re-retrieved. Only that grounded
re-retrieval may replace the initial corpus report as synthesis input.

Grounded completion is explicit opt-in because it performs side-effecting acquisition
and local-model grounding work. It requires a discovery policy with acquisition-plan
requests enabled. Discovery candidates and merely acquired papers are never passed to
synthesis directly.
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
from knowledge_engine_ai.copilot.grounded_completion import (
    GroundedCompletionPolicy,
    GroundedCompletionResult,
    complete_discovered_research,
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
from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository
from knowledge_engine_ai.synthesis import synthesize_answer

_ISA_SCHEMA_VERSION = 1
_WORKFLOW_INTEGRITY_CRITERION_ID = "workflow_integrity"
_CITATION_INTEGRITY_CRITERION_ID = "citation_integrity"
_CONTRADICTION_REVIEW_CRITERION_ID = "contradiction_review"
_DISCOVERY_COVERAGE_CRITERION_ID = "discovery_coverage"
_GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID = "grounded_completion_integrity"

_SYNTHESIS_NODE = "synthesis"
_SYNTHESIS_EXECUTOR_TYPE = "local_llm"
_GROUNDED_EXECUTOR_TYPE = "deterministic_tool"
_GROUNDED_ACQUISITION_NODE = "grounded_acquisition"
_GROUNDED_EXTRACTION_NODE = "grounded_extraction"
_GROUNDED_RERETRIEVAL_NODE = "grounded_reretrieval"


@dataclass(frozen=True)
class ResearchQuestionResult:
    """The full assembled outcome of one question-to-answer research session.

    ``workflow`` always preserves the initial corpus retrieval result.
    ``grounded_completion`` is present only when the caller opted into GQR-4/GQR-5.
    When that completion produced a grounded ``reretrieval_report``, it is the report
    used for synthesis, verification, and the session report. This keeps the original
    retrieval auditable without letting a pre-grounding discovery result become an
    answer source.
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
    grounded_completion: GroundedCompletionResult | None = None

    @property
    def narrative_releaseable(self) -> bool:
        """Whether the draft narrative passed every deterministic release gate."""

        return (
            self.narrative is not None
            and self.verification is not None
            and self.verification.is_clean
            and self.close_result.status is SessionStatus.COMPLETED
        )

    @property
    def effective_evidence_report(self) -> EvidenceReport | None:
        """The exact report used for synthesis/verification in this session."""

        if (
            self.grounded_completion is not None
            and self.grounded_completion.reretrieval_report is not None
        ):
            return self.grounded_completion.reretrieval_report
        return self.workflow.evidence_report

    @property
    def used_reretrieved_evidence(self) -> bool:
        """Whether grounded GQR-5 re-retrieval replaced the initial report for synthesis."""

        return (
            self.grounded_completion is not None
            and self.grounded_completion.reretrieval_report is not None
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
    grounded_completion_policy: GroundedCompletionPolicy | None = None,
    research_question_id: str | None = None,
    answer_version: int = 1,
    supersedes_session_id: str | None = None,
    ke_executable: str = "ke",
    timeout_seconds: float | None = None,
) -> ResearchQuestionResult:
    """Create one session and run retrieval, optional grounded completion, and synthesis.

    Grounded completion is fail-closed at configuration time: a caller cannot request
    acquisition/extraction without also opting into discovery and its acquisition-plan
    step, and both policies must point at the same federated-search ledger. The
    completion itself remains evidence-safe: only its final grounded re-retrieval may
    replace the initial corpus report as synthesis input.
    """

    _validate_grounded_completion_configuration(discovery_policy, grounded_completion_policy)

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

    grounded_completion: GroundedCompletionResult | None = None
    synthesis_evidence_report = workflow_result.evidence_report
    if grounded_completion_policy is not None:
        # Configuration validation above guarantees a discovery policy, and therefore
        # the augmentation result, exists on this opt-in path.
        assert discovery_augmentation is not None
        grounded_completion = complete_discovered_research(
            question,
            discovery=discovery_augmentation,
            sources=sources,
            evidence=evidence,
            policy=grounded_completion_policy,
            ke_executable=ke_executable,
            execution_budget=execution_budget,
        )
        _record_grounded_completion_events(
            session_repository,
            session_id=session_id,
            result=grounded_completion,
        )
        if grounded_completion.reretrieval_report is not None:
            synthesis_evidence_report = grounded_completion.reretrieval_report

    narrative, synthesis_error = _synthesize(
        session_repository=session_repository,
        session_id=session_id,
        evidence_report=synthesis_evidence_report,
        llm=llm,
        execution_budget=execution_budget,
    )

    verification: VerificationResult | None = None
    session_report: SessionReport | None = None
    if narrative is not None and synthesis_evidence_report is not None:
        verification = verify_synthesis(narrative, synthesis_evidence_report)
        session_report = build_session_report(narrative, synthesis_evidence_report, verification)

    session_repository.attach_research_isa(
        session_id,
        _build_isa(
            session_id,
            question,
            discovery_policy_supplied=discovery_policy is not None,
            grounded_completion_policy_supplied=grounded_completion_policy is not None,
        ),
    )
    recorded_at = _timestamp()
    for result in _isa_criterion_results(
        workflow_result,
        verification,
        discovery_augmentation,
        grounded_completion,
        grounded_completion_policy_supplied=grounded_completion_policy is not None,
    ):
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
        grounded_completion=grounded_completion,
        narrative=narrative,
        synthesis_error=synthesis_error,
        verification=verification,
        session_report=session_report,
        close_result=close_result,
        trace=trace,
    )


def _validate_grounded_completion_configuration(
    discovery_policy: FederatedDiscoveryPolicy | None,
    grounded_completion_policy: GroundedCompletionPolicy | None,
) -> None:
    if grounded_completion_policy is None:
        return
    if discovery_policy is None:
        raise ValueError("grounded_completion_policy requires discovery_policy.")
    if not discovery_policy.enable_acquisition_plan:
        raise ValueError(
            "grounded_completion_policy requires discovery_policy.enable_acquisition_plan=True."
        )
    discovery_ledger = discovery_policy.ledger_root.resolve(strict=False)
    completion_ledger = grounded_completion_policy.ledger_root.resolve(strict=False)
    if discovery_ledger != completion_ledger:
        raise ValueError(
            "discovery_policy and grounded_completion_policy must use the same ledger_root."
        )


def _synthesize(
    *,
    session_repository: SessionRepository,
    session_id: str,
    evidence_report: EvidenceReport | None,
    llm: LocalLLM,
    execution_budget: ExecutionBudget | None,
) -> tuple[str | None, str | None]:
    """Run synthesis and append exactly one durable synthesis event when a report exists."""

    if evidence_report is None:
        return None, None

    source_ids, source_dois = _report_sources(evidence_report)
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
            source_ids=source_ids,
            source_dois=source_dois,
        )
        return None, str(exc)

    if narrative is None:
        _record_synthesis_event(
            session_repository,
            session_id=session_id,
            output="No evidence with a stated claim was retrieved to synthesize from.",
            error=None,
            duration_ms=_elapsed_ms(start),
            source_ids=source_ids,
            source_dois=source_dois,
        )
        return None, None

    _record_synthesis_event(
        session_repository,
        session_id=session_id,
        output=narrative,
        error=None,
        duration_ms=_elapsed_ms(start),
        source_ids=source_ids,
        source_dois=source_dois,
    )
    return narrative, None


def _record_synthesis_event(
    session_repository: SessionRepository,
    *,
    session_id: str,
    output: str | None,
    error: str | None,
    duration_ms: int,
    source_ids: tuple[str, ...] = (),
    source_dois: tuple[str, ...] = (),
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
            source_ids=source_ids,
            source_dois=source_dois,
            notes=error if error is not None else output,
            duration_ms=duration_ms,
        )
    )


def _record_grounded_completion_events(
    session_repository: SessionRepository,
    *,
    session_id: str,
    result: GroundedCompletionResult,
) -> None:
    acquisition_status = _grounded_acquisition_status(result)
    acquisition_notes = _grounded_acquisition_notes(result)
    _record_grounded_event(
        session_repository,
        session_id=session_id,
        workflow_node=_GROUNDED_ACQUISITION_NODE,
        tool_name="ke general-question-acquire-*",
        validation_status=acquisition_status,
        notes=acquisition_notes,
    )

    extraction_status = _grounded_extraction_status(result)
    extraction_notes = _grounded_extraction_notes(result)
    _record_grounded_event(
        session_repository,
        session_id=session_id,
        workflow_node=_GROUNDED_EXTRACTION_NODE,
        tool_name="ke extraction-review / evidence-review-automate",
        validation_status=extraction_status,
        notes=extraction_notes,
    )

    reretrieval_status = _grounded_reretrieval_status(result)
    reretrieval_notes = _grounded_reretrieval_notes(result)
    source_ids: tuple[str, ...] = ()
    source_dois: tuple[str, ...] = ()
    output_schema_version: int | None = None
    if result.reretrieval_report is not None:
        source_ids, source_dois = _report_sources(result.reretrieval_report)
        output_schema_version = result.reretrieval_report.schema_version
    _record_grounded_event(
        session_repository,
        session_id=session_id,
        workflow_node=_GROUNDED_RERETRIEVAL_NODE,
        tool_name="ke evidence-report",
        validation_status=reretrieval_status,
        notes=reretrieval_notes,
        output_schema_version=output_schema_version,
        source_ids=source_ids,
        source_dois=source_dois,
    )


def _record_grounded_event(
    session_repository: SessionRepository,
    *,
    session_id: str,
    workflow_node: str,
    tool_name: str,
    validation_status: str,
    notes: str,
    output_schema_version: int | None = None,
    source_ids: tuple[str, ...] = (),
    source_dois: tuple[str, ...] = (),
) -> None:
    session_repository.append_event(
        ResearchEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=_timestamp(),
            workflow_node=workflow_node,
            executor_type=_GROUNDED_EXECUTOR_TYPE,
            validation_status=validation_status,
            output_schema_version=output_schema_version,
            output_hash=_hash(notes),
            tool_name=tool_name,
            source_ids=source_ids,
            source_dois=source_dois,
            notes=notes,
        )
    )


def _grounded_acquisition_status(result: GroundedCompletionResult) -> str:
    if not result.attempted:
        return "skipped"
    if result.paper_ids:
        return "succeeded"
    if any(route.error for route in result.acquisition_routes):
        return "failed"
    return "skipped"


def _grounded_extraction_status(result: GroundedCompletionResult) -> str:
    if not result.attempted or not result.paper_ids:
        return "skipped"
    if result.extraction_error is not None:
        return "failed"
    return "succeeded"


def _grounded_reretrieval_status(result: GroundedCompletionResult) -> str:
    if result.reretrieval_error is not None:
        return "failed"
    if result.reretrieval_report is not None:
        return "succeeded"
    return "skipped"


def _grounded_acquisition_notes(result: GroundedCompletionResult) -> str:
    if not result.attempted:
        return f"Grounded acquisition skipped: {result.skipped_reason or 'no acquisition plan.'}"
    route_failures = tuple(
        f"{route.route}: {route.error}" for route in result.acquisition_routes if route.error
    )
    persisted = sum(route.persisted_count for route in result.acquisition_routes)
    reused = sum(route.reused_count for route in result.acquisition_routes)
    return (
        f"search_run_id={result.search_run_id}; papers_available={len(result.paper_ids)}; "
        f"new_papers={persisted}; reused_papers={reused}; "
        f"already_indexed={len(result.already_indexed_paper_ids)}; "
        f"route_failures={list(route_failures)}. "
        "Acquired/reused Papers are not yet answer evidence."
    )


def _grounded_extraction_notes(result: GroundedCompletionResult) -> str:
    if not result.attempted or not result.paper_ids:
        return (
            "Grounded extraction skipped because no persisted/reusable paper reached the "
            "extraction stage."
        )
    if result.extraction_error is not None:
        return f"Grounded extraction failed: {result.extraction_error}"
    return (
        f"draft_items={result.draft_item_count}; classified_items={result.classified_item_count}; "
        f"staged={len(result.staged_record_ids)}; grounded={len(result.grounded_record_ids)}; "
        f"promoted={len(result.promoted_record_ids)}; "
        f"grounding_failures={list(result.grounding_failures)}. "
        "Only grounded/reviewed records were eligible for durable promotion."
    )


def _grounded_reretrieval_notes(result: GroundedCompletionResult) -> str:
    if result.reretrieval_error is not None:
        return f"Original-question grounded re-retrieval failed: {result.reretrieval_error}"
    if result.reretrieval_report is None:
        reason = result.skipped_reason or "no newly promoted grounded EvidenceRecord"
        return f"Grounded re-retrieval skipped: {reason}."
    source_ids, _ = _report_sources(result.reretrieval_report)
    return (
        f"Grounded re-retrieval succeeded with {len(result.reretrieval_report.papers)} paper(s) "
        f"and {len(source_ids)} EvidenceRecord(s). This report is eligible for synthesis."
    )


def _build_isa(
    session_id: str,
    question: str,
    *,
    discovery_policy_supplied: bool,
    grounded_completion_policy_supplied: bool = False,
) -> ResearchISA:
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
        criteria = (
            *criteria,
            IdealStateCriterion(
                criterion_id=_DISCOVERY_COVERAGE_CRITERION_ID,
                claim=(
                    "If federated discovery was triggered to broaden thin corpus coverage, "
                    "every attempted provider succeeded; provider failures remain explicit."
                ),
                probe="discovery_augmentation: federated_discovery.completeness == 'complete'",
                required=False,
            ),
        )
    if grounded_completion_policy_supplied:
        criteria = (
            *criteria,
            IdealStateCriterion(
                criterion_id=_GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
                claim=(
                    "Requested grounded completion was either unnecessary or reached its "
                    "furthest applicable stage without a hard acquisition, extraction, or "
                    "re-retrieval execution failure."
                ),
                probe="grounded_completion: no hard pipeline error",
            ),
        )
    return ResearchISA(
        schema_version=_ISA_SCHEMA_VERSION,
        run_id=f"run-{session_id}",
        question=question,
        ideal_state=(
            "A synthesized answer whose every citation is grounded in retrieved evidence and "
            "which does not silently omit contradicting or qualifying evidence, or an honest "
            "statement that the bounded research path found no usable evidence."
        ),
        criteria=criteria,
    )


def _isa_criterion_results(
    workflow_result: WorkflowResult,
    verification: VerificationResult | None,
    discovery_augmentation: DiscoveryAugmentationResult | None,
    grounded_completion: GroundedCompletionResult | None = None,
    *,
    grounded_completion_policy_supplied: bool = False,
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
        results: tuple[CriterionResult, ...] = (
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

    if discovery_augmentation is not None:
        results = (*results, _discovery_coverage_result(discovery_augmentation))
    if grounded_completion_policy_supplied:
        results = (
            *results,
            _grounded_completion_integrity_result(discovery_augmentation, grounded_completion),
        )
    return results


def _grounded_completion_integrity_result(
    discovery_augmentation: DiscoveryAugmentationResult | None,
    grounded_completion: GroundedCompletionResult | None,
) -> CriterionResult:
    if discovery_augmentation is None:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            "Grounded completion was requested but no discovery augmentation was recorded.",
        )

    if not discovery_augmentation.triggered:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.PASSED,
            "Initial evidence coverage was sufficient; grounded completion was unnecessary.",
        )

    if discovery_augmentation.federated_discovery_error is not None:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            "Federated discovery failed before grounded completion could run: "
            f"{discovery_augmentation.federated_discovery_error}",
        )
    if discovery_augmentation.acquisition_plan_error is not None:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            "Acquisition planning failed before grounded completion could run: "
            f"{discovery_augmentation.acquisition_plan_error}",
        )
    if grounded_completion is None:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            "Grounded completion was requested but produced no completion result.",
        )
    if grounded_completion.extraction_error is not None:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            f"Grounded extraction failed: {grounded_completion.extraction_error}",
        )
    if grounded_completion.reretrieval_error is not None:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            f"Grounded re-retrieval failed: {grounded_completion.reretrieval_error}",
        )

    route_failures = tuple(
        f"{route.route}: {route.error}"
        for route in grounded_completion.acquisition_routes
        if route.error is not None
    )
    if grounded_completion.attempted and not grounded_completion.paper_ids and route_failures:
        return CriterionResult(
            _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
            CriterionStatus.FAILED,
            f"Every usable acquisition path failed: {list(route_failures)}",
        )

    if grounded_completion.reretrieval_report is not None:
        evidence = (
            f"Grounded completion promoted {len(grounded_completion.promoted_record_ids)} "
            "EvidenceRecord(s) and re-ran the original question successfully."
        )
    elif grounded_completion.attempted:
        evidence = (
            "Grounded completion ran without a hard execution failure but produced no newly "
            "promoted evidence eligible for re-retrieval."
        )
    else:
        evidence = grounded_completion.skipped_reason or (
            "Discovery produced no acquisition plan/candidate requiring grounded completion."
        )
    return CriterionResult(
        _GROUNDED_COMPLETION_INTEGRITY_CRITERION_ID,
        CriterionStatus.PASSED,
        evidence,
    )


def _discovery_coverage_result(
    discovery_augmentation: DiscoveryAugmentationResult,
) -> CriterionResult:
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


def _report_sources(report: EvidenceReport) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Deduplicate EvidenceRecord IDs and retain each record's paper DOI in parallel."""

    pairs: dict[str, str] = {}
    for paper in report.papers:
        for record in paper.evidence_records:
            evidence_record_id = record.evidence_record_id
            if evidence_record_id and evidence_record_id not in pairs:
                pairs[evidence_record_id] = paper.doi
    return tuple(pairs), tuple(pairs.values())


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _derive_research_question_id(question: str) -> str:
    normalized = question.strip().lower()
    return f"rq-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


__all__ = ["ResearchQuestionResult", "run_research_question"]
