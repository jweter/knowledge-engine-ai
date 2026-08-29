"""GQR-4/GQR-5 bridge from acquisition plans to grounded re-retrieval.

This module closes the first executable path between Core discovery candidates
and an EvidenceReport that may be used for synthesis:

acquisition plan -> bounded acquisition -> persisted Papers -> extraction queue
-> automated classification -> private staged EvidenceRecords -> Core grounding
verification -> Core review promotion -> durable Core promotion -> re-retrieval.

The private staging file is the trust boundary. Raw automated records are never
written to the caller's evidence file. Only records Core reports as both
``llm_grounded`` and ``reviewed`` are submitted back through Core's EvidenceRecord
promotion validator for durable persistence.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded
from knowledge_engine_ai.ke_client import (
    GeneralQuestionAcquisitionPlanResult,
    KeCommandError,
    _resolve_ke_executable,
    _run_ke_command,
    evidence_report,
)
from knowledge_engine_ai.models import EvidenceReport

_ELIGIBLE_FULL_TEXT = "eligible_full_text"
_ALREADY_INDEXED = "already_indexed"
_ROUTE_COMMANDS: dict[str, str] = {
    "pmc_oa": "general-question-acquire-pmc",
    "europe_pmc_oa": "general-question-acquire-europe-pmc",
    "core": "general-question-acquire-core",
    "unpaywall": "general-question-acquire-unpaywall",
}

#: BT-7 default: the number of newly promoted grounded EvidenceRecords that is
#: considered sufficient to skip further optional acquisition breadth. Matches
#: ``discovery_policy.DEFAULT_MIN_EVIDENCE_RECORD_COVERAGE`` so "adequate
#: coverage" means the same thing before and after federated discovery.
DEFAULT_MIN_PROMOTED_RECORDS_FOR_EARLY_STOP = 3

_ADEQUACY_SKIP_REASON = "already-indexed evidence met the adequacy threshold before acquisition"


class GroundedCompletionPolicyError(ValueError):
    """A grounded-completion policy contains an unsafe or unbounded value."""


class GroundedCompletionContractError(RuntimeError):
    """Core returned a receipt that cannot be reconciled to the requested route."""


@dataclass(frozen=True)
class GroundedCompletionPolicy:
    """Explicit bounds and Core filesystem context for one completion pass."""

    ledger_root: Path
    papers_dir: Path
    grounding_model: str
    core_working_directory: Path | None = None
    max_acquisition_routes: int = 4
    max_candidates_per_route: int = 10
    max_full_text_acquisitions_per_route: int = 5
    max_elapsed_seconds_per_route: int = 120
    max_promoted_records: int = 12
    reretrieval_limit: int = 5
    min_promoted_records_for_early_stop: int = DEFAULT_MIN_PROMOTED_RECORDS_FOR_EARLY_STOP

    def __post_init__(self) -> None:
        if not self.grounding_model.strip():
            raise GroundedCompletionPolicyError("grounding_model must be non-blank.")
        if not 1 <= self.max_acquisition_routes <= len(_ROUTE_COMMANDS):
            raise GroundedCompletionPolicyError(
                f"max_acquisition_routes must be between 1 and {len(_ROUTE_COMMANDS)}."
            )
        if not 1 <= self.max_candidates_per_route <= 100:
            raise GroundedCompletionPolicyError("max_candidates_per_route must be 1..100.")
        if not 1 <= self.max_full_text_acquisitions_per_route <= self.max_candidates_per_route:
            raise GroundedCompletionPolicyError(
                "max_full_text_acquisitions_per_route must be between 1 and "
                "max_candidates_per_route."
            )
        if not 1 <= self.max_elapsed_seconds_per_route <= 600:
            raise GroundedCompletionPolicyError(
                "max_elapsed_seconds_per_route must be between 1 and 600."
            )
        if not 1 <= self.max_promoted_records <= 100:
            raise GroundedCompletionPolicyError("max_promoted_records must be 1..100.")
        if not 1 <= self.reretrieval_limit <= 100:
            raise GroundedCompletionPolicyError("reretrieval_limit must be 1..100.")
        if not 1 <= self.min_promoted_records_for_early_stop <= self.max_promoted_records:
            raise GroundedCompletionPolicyError(
                "min_promoted_records_for_early_stop must be between 1 and max_promoted_records."
            )


@dataclass(frozen=True)
class AcquisitionRouteResult:
    """One acquisition attempt's durable outcome.

    A route may yield multiple results when the caller intentionally isolates
    candidates to keep one strict Core validation failure from discarding other
    independently valid papers on the same route.
    """

    route: str
    candidate_ids: tuple[str, ...]
    attempted: bool
    paper_ids: tuple[int, ...] = ()
    import_run_id: str | None = None
    persisted_count: int = 0
    reused_count: int = 0
    error: str | None = None
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "route": self.route,
            "candidate_ids": list(self.candidate_ids),
            "attempted": self.attempted,
            "paper_ids": list(self.paper_ids),
            "import_run_id": self.import_run_id,
            "persisted_count": self.persisted_count,
            "reused_count": self.reused_count,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True)
class GroundedCompletionResult:
    """Structured GQR-4/GQR-5 outcome for one discovery augmentation."""

    attempted: bool
    search_run_id: str | None
    research_question_id: str | None
    already_indexed_paper_ids: tuple[int, ...] = ()
    acquisition_routes: tuple[AcquisitionRouteResult, ...] = ()
    paper_ids: tuple[int, ...] = ()
    draft_item_count: int = 0
    classified_item_count: int = 0
    staged_record_ids: tuple[str, ...] = ()
    grounded_record_ids: tuple[str, ...] = ()
    promoted_record_ids: tuple[str, ...] = ()
    grounding_failures: tuple[str, ...] = ()
    extraction_error: str | None = None
    reretrieval_report: EvidenceReport | None = None
    reretrieval_error: str | None = None
    acquisition_duration_ms: int | None = None
    extraction_duration_ms: int | None = None
    reretrieval_duration_ms: int | None = None
    skipped_reason: str | None = None
    acquisition_skipped_for_adequacy: bool = False

    @property
    def completed_with_new_evidence(self) -> bool:
        return bool(self.promoted_record_ids and self.reretrieval_report is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "search_run_id": self.search_run_id,
            "research_question_id": self.research_question_id,
            "already_indexed_paper_ids": list(self.already_indexed_paper_ids),
            "acquisition_routes": [route.to_dict() for route in self.acquisition_routes],
            "paper_ids": list(self.paper_ids),
            "draft_item_count": self.draft_item_count,
            "classified_item_count": self.classified_item_count,
            "staged_record_ids": list(self.staged_record_ids),
            "grounded_record_ids": list(self.grounded_record_ids),
            "promoted_record_ids": list(self.promoted_record_ids),
            "grounding_failures": list(self.grounding_failures),
            "extraction_error": self.extraction_error,
            "reretrieval_error": self.reretrieval_error,
            "acquisition_duration_ms": self.acquisition_duration_ms,
            "extraction_duration_ms": self.extraction_duration_ms,
            "reretrieval_duration_ms": self.reretrieval_duration_ms,
            "completed_with_new_evidence": self.completed_with_new_evidence,
            "skipped_reason": self.skipped_reason,
            "acquisition_skipped_for_adequacy": self.acquisition_skipped_for_adequacy,
        }


@dataclass(frozen=True)
class _ExtractionResult:
    draft_item_count: int
    classified_item_count: int
    staged_record_ids: tuple[str, ...]
    grounded_record_ids: tuple[str, ...]
    promoted_record_ids: tuple[str, ...]
    grounding_failures: tuple[str, ...] = ()


def complete_discovered_research(
    question: str,
    *,
    discovery: DiscoveryAugmentationResult,
    sources: Path,
    evidence: Path,
    policy: GroundedCompletionPolicy,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> GroundedCompletionResult:
    """Acquire, ground, promote, and re-retrieve one discovery augmentation.

    BT-7 (issue #92): already-indexed candidates cost nothing to acquire, so they
    are extracted/grounded/promoted first, before any network acquisition. If that
    alone promotes at least ``policy.min_promoted_records_for_early_stop`` grounded
    EvidenceRecords, the bounded research path is already adequate and every
    configured acquisition route is skipped -- recorded as an explicit,
    inspectable ``AcquisitionRouteResult(attempted=False, skipped_reason=...)``
    rather than silently omitted. Otherwise acquisition proceeds across every
    configured route exactly as before, and the newly acquired papers are
    extracted/promoted in one additional bounded batch. This never lets a
    discovery candidate bypass EvidenceRecord validation; it only decides whether
    already-validated coverage makes further optional breadth necessary.

    Acquisition-route failures are retained as degraded route results and do not
    erase successful routes. PMC candidates are deliberately isolated because Core's
    PMC executor is validation-atomic: one candidate that no longer has independently
    verified reusable full text must not discard other candidates that still pass
    Core's strict verification. An extraction-batch failure stops that batch's
    new-evidence path before re-retrieval, preventing an ungrounded staged record
    from entering synthesis, but does not discard grounded records a prior batch
    already promoted durably.
    """

    plan = discovery.acquisition_plan
    if plan is None:
        return GroundedCompletionResult(
            attempted=False,
            search_run_id=(
                discovery.federated_discovery.search_run_id
                if discovery.federated_discovery is not None
                else None
            ),
            research_question_id=None,
            skipped_reason=(
                discovery.acquisition_plan_skipped_reason
                or discovery.acquisition_plan_error
                or "no acquisition plan available"
            ),
        )

    already_indexed = _already_indexed_paper_ids(plan)
    route_candidates = _route_candidates(plan)[: policy.max_acquisition_routes]

    extraction = _ExtractionResult(0, 0, (), (), ())
    extraction_error: str | None = None
    processed_paper_ids: list[int] = []
    extraction_duration_start = time.monotonic()

    if already_indexed:
        processed_paper_ids.extend(already_indexed)
        try:
            extraction = _extract_ground_promote(
                already_indexed,
                evidence=evidence,
                policy=policy,
                ke_executable=ke_executable,
                execution_budget=execution_budget,
            )
        except KeCommandError as exc:
            extraction_error = str(exc)

    adequate_from_indexed = extraction_error is None and (
        len(extraction.promoted_record_ids) >= policy.min_promoted_records_for_early_stop
    )

    route_results: list[AcquisitionRouteResult] = []
    acquisition_duration_ms: int | None = None
    acquisition_skipped_for_adequacy = False

    if extraction_error is None and route_candidates:
        if adequate_from_indexed:
            acquisition_skipped_for_adequacy = True
            acquisition_duration_ms = 0
            route_results.extend(
                AcquisitionRouteResult(
                    route=route,
                    candidate_ids=candidate_ids,
                    attempted=False,
                    skipped_reason=_ADEQUACY_SKIP_REASON,
                )
                for route, candidate_ids in route_candidates
            )
        else:
            acquisition_start = time.monotonic()
            acquired_paper_ids: list[int] = []
            for route, candidate_ids in route_candidates:
                results = _execute_acquisition_route_attempts(
                    plan,
                    route=route,
                    candidate_ids=candidate_ids,
                    policy=policy,
                    ke_executable=ke_executable,
                    execution_budget=execution_budget,
                )
                route_results.extend(results)
                for result in results:
                    acquired_paper_ids.extend(result.paper_ids)
            acquisition_duration_ms = _elapsed_ms(acquisition_start)

            newly_acquired = tuple(
                dict.fromkeys(pid for pid in acquired_paper_ids if pid not in processed_paper_ids)
            )
            if newly_acquired:
                processed_paper_ids.extend(newly_acquired)
                try:
                    acquired_extraction = _extract_ground_promote(
                        newly_acquired,
                        evidence=evidence,
                        policy=policy,
                        ke_executable=ke_executable,
                        execution_budget=execution_budget,
                    )
                    extraction = _merge_extraction_results(extraction, acquired_extraction)
                except KeCommandError as exc:
                    extraction_error = str(exc)

    paper_ids = tuple(processed_paper_ids)
    if not paper_ids:
        return GroundedCompletionResult(
            attempted=True,
            search_run_id=plan.search_run_id,
            research_question_id=plan.research_question_id,
            acquisition_routes=tuple(route_results),
            acquisition_duration_ms=acquisition_duration_ms,
            skipped_reason="no persisted or reusable paper was available for grounded extraction",
        )

    extraction_duration_ms = _elapsed_ms(extraction_duration_start)
    if extraction_error is not None and not extraction.promoted_record_ids:
        return GroundedCompletionResult(
            attempted=True,
            search_run_id=plan.search_run_id,
            research_question_id=plan.research_question_id,
            already_indexed_paper_ids=already_indexed,
            acquisition_routes=tuple(route_results),
            paper_ids=paper_ids,
            acquisition_duration_ms=acquisition_duration_ms,
            extraction_duration_ms=extraction_duration_ms,
            extraction_error=extraction_error,
            acquisition_skipped_for_adequacy=acquisition_skipped_for_adequacy,
        )

    reretrieval: EvidenceReport | None = None
    reretrieval_error: str | None = None
    reretrieval_duration_ms: int | None = None
    if extraction.promoted_record_ids:
        reretrieval_start = time.monotonic()
        try:
            reretrieval = evidence_report(
                question,
                sources=sources,
                evidence=evidence,
                limit=policy.reretrieval_limit,
                ke_executable=ke_executable,
                execution_budget=execution_budget,
                working_directory=policy.core_working_directory,
            )
        except KeCommandError as exc:
            reretrieval_error = str(exc)
        reretrieval_duration_ms = _elapsed_ms(reretrieval_start)

    return GroundedCompletionResult(
        attempted=True,
        search_run_id=plan.search_run_id,
        research_question_id=plan.research_question_id,
        already_indexed_paper_ids=already_indexed,
        acquisition_routes=tuple(route_results),
        paper_ids=paper_ids,
        draft_item_count=extraction.draft_item_count,
        classified_item_count=extraction.classified_item_count,
        staged_record_ids=extraction.staged_record_ids,
        grounded_record_ids=extraction.grounded_record_ids,
        promoted_record_ids=extraction.promoted_record_ids,
        grounding_failures=extraction.grounding_failures,
        extraction_error=extraction_error,
        reretrieval_report=reretrieval,
        reretrieval_error=reretrieval_error,
        acquisition_duration_ms=acquisition_duration_ms,
        extraction_duration_ms=extraction_duration_ms,
        reretrieval_duration_ms=reretrieval_duration_ms,
        acquisition_skipped_for_adequacy=acquisition_skipped_for_adequacy,
        skipped_reason=(
            "no automatically classified record passed grounded review"
            if not extraction.promoted_record_ids
            else None
        ),
    )


def _already_indexed_paper_ids(plan: GeneralQuestionAcquisitionPlanResult) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                item.existing_paper_id
                for item in plan.items
                if item.disposition == _ALREADY_INDEXED and item.existing_paper_id is not None
            }
        )
    )


def _route_candidates(
    plan: GeneralQuestionAcquisitionPlanResult,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    grouped: dict[str, list[str]] = {}
    for item in plan.items:
        if item.disposition != _ELIGIBLE_FULL_TEXT or item.acquisition_route is None:
            continue
        if item.acquisition_route in _ROUTE_COMMANDS:
            grouped.setdefault(item.acquisition_route, []).append(item.candidate_id)
    return tuple((route, tuple(grouped[route])) for route in _ROUTE_COMMANDS if route in grouped)


def _execute_acquisition_route_attempts(
    plan: GeneralQuestionAcquisitionPlanResult,
    *,
    route: str,
    candidate_ids: tuple[str, ...],
    policy: GroundedCompletionPolicy,
    ke_executable: str,
    execution_budget: ExecutionBudget | None,
) -> tuple[AcquisitionRouteResult, ...]:
    """Execute one planned route, isolating PMC candidates under one route deadline."""

    bounded_ids = candidate_ids[: policy.max_candidates_per_route]
    if not bounded_ids:
        return ()

    if route != "pmc_oa":
        try:
            result = _execute_acquisition_route(
                plan,
                route=route,
                candidate_ids=bounded_ids,
                policy=policy,
                ke_executable=ke_executable,
                execution_budget=execution_budget,
            )
        except (KeCommandError, GroundedCompletionContractError, ExecutionBudgetExceeded) as exc:
            result = AcquisitionRouteResult(
                route=route,
                candidate_ids=bounded_ids,
                attempted=True,
                error=str(exc),
            )
        return (result,)

    isolated_ids = bounded_ids[: policy.max_full_text_acquisitions_per_route]
    route_deadline = time.monotonic() + policy.max_elapsed_seconds_per_route
    if execution_budget is not None:
        route_deadline = min(route_deadline, execution_budget.deadline_monotonic)

    results: list[AcquisitionRouteResult] = []
    for candidate_id in isolated_ids:
        route_budget = ExecutionBudget(deadline_monotonic=route_deadline)
        try:
            remaining_seconds = route_budget.remaining_seconds()
        except ExecutionBudgetExceeded as exc:
            results.append(
                AcquisitionRouteResult(
                    route=route,
                    candidate_ids=(candidate_id,),
                    attempted=False,
                    error=f"{candidate_id}: {exc}",
                )
            )
            break

        request_elapsed_seconds = max(
            1,
            min(policy.max_elapsed_seconds_per_route, int(remaining_seconds)),
        )
        try:
            result = _execute_acquisition_route(
                plan,
                route=route,
                candidate_ids=(candidate_id,),
                policy=policy,
                ke_executable=ke_executable,
                execution_budget=route_budget,
                max_elapsed_seconds=request_elapsed_seconds,
            )
        except ExecutionBudgetExceeded as exc:
            results.append(
                AcquisitionRouteResult(
                    route=route,
                    candidate_ids=(candidate_id,),
                    attempted=True,
                    error=f"{candidate_id}: {exc}",
                )
            )
            break
        except (KeCommandError, GroundedCompletionContractError) as exc:
            results.append(
                AcquisitionRouteResult(
                    route=route,
                    candidate_ids=(candidate_id,),
                    attempted=True,
                    error=f"{candidate_id}: {exc}",
                )
            )
            continue
        results.append(result)
    return tuple(results)


def _execute_acquisition_route(
    plan: GeneralQuestionAcquisitionPlanResult,
    *,
    route: str,
    candidate_ids: tuple[str, ...],
    policy: GroundedCompletionPolicy,
    ke_executable: str,
    execution_budget: ExecutionBudget | None,
    max_elapsed_seconds: int | None = None,
) -> AcquisitionRouteResult:
    command_name = _ROUTE_COMMANDS[route]
    bounded_ids = candidate_ids[: policy.max_candidates_per_route]
    elapsed_limit = max_elapsed_seconds or policy.max_elapsed_seconds_per_route
    request_payload = {
        "schema_version": 1,
        "search_run_id": plan.search_run_id,
        "research_question_id": plan.research_question_id,
        "candidate_ids": list(bounded_ids),
        "max_candidates": len(bounded_ids),
        "max_full_text_acquisitions": min(
            len(bounded_ids), policy.max_full_text_acquisitions_per_route
        ),
        "max_elapsed_seconds": elapsed_limit,
        "allow_metadata_only": True,
    }

    with tempfile.TemporaryDirectory(prefix=f"ke-gqr-{route}-") as scratch:
        root = Path(scratch)
        request_path = root / "request.json"
        receipt_path = root / "receipt.json"
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")
        command = [
            _resolve_ke_executable(ke_executable),
            command_name,
            str(request_path),
            "--ledger-root",
            str(policy.ledger_root),
            "--papers-dir",
            str(policy.papers_dir),
            "--receipt",
            str(receipt_path),
        ]
        _run_checked(
            command,
            operation=f"ke {command_name}",
            policy=policy,
            execution_budget=execution_budget,
        )
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(
                f"`ke {command_name}` did not write a readable receipt: {exc}"
            ) from exc

    return _parse_acquisition_receipt(
        payload,
        route=route,
        candidate_ids=bounded_ids,
        search_run_id=plan.search_run_id,
        research_question_id=plan.research_question_id,
    )


def _parse_acquisition_receipt(
    payload: dict[str, Any],
    *,
    route: str,
    candidate_ids: tuple[str, ...],
    search_run_id: str,
    research_question_id: str,
) -> AcquisitionRouteResult:
    try:
        receipt_search_run_id = payload["search_run_id"]
        receipt_research_question_id = payload["research_question_id"]
        receipt_route = payload["acquisition_route"]
        import_run_id = payload["import_run_id"]
        persisted_count = payload["persisted_count"]
        reused_count = payload["reused_count"]
        items = payload["items"]
    except (KeyError, TypeError) as exc:
        raise GroundedCompletionContractError(
            f"Acquisition receipt is missing a required field: {exc}"
        ) from exc

    if (
        receipt_search_run_id != search_run_id
        or receipt_research_question_id != research_question_id
        or receipt_route != route
    ):
        raise GroundedCompletionContractError(
            "Acquisition receipt provenance does not match the requested research route."
        )
    if not isinstance(items, list):
        raise GroundedCompletionContractError("Acquisition receipt items must be a list.")
    try:
        received_candidate_ids = tuple(str(item["candidate_id"]) for item in items)
        paper_ids = tuple(int(item["paper_id"]) for item in items)
    except (KeyError, TypeError, ValueError) as exc:
        raise GroundedCompletionContractError(
            f"Acquisition receipt contains a malformed item: {exc}"
        ) from exc
    if set(received_candidate_ids) != set(candidate_ids):
        raise GroundedCompletionContractError(
            "Acquisition receipt candidate identities do not match the requested route."
        )

    return AcquisitionRouteResult(
        route=route,
        candidate_ids=candidate_ids,
        attempted=True,
        paper_ids=paper_ids,
        import_run_id=str(import_run_id),
        persisted_count=int(persisted_count),
        reused_count=int(reused_count),
    )


def _merge_extraction_results(
    first: _ExtractionResult, second: _ExtractionResult
) -> _ExtractionResult:
    """Combine two bounded extraction batches into one cumulative BT-7 result."""

    return _ExtractionResult(
        draft_item_count=first.draft_item_count + second.draft_item_count,
        classified_item_count=first.classified_item_count + second.classified_item_count,
        staged_record_ids=first.staged_record_ids + second.staged_record_ids,
        grounded_record_ids=first.grounded_record_ids + second.grounded_record_ids,
        promoted_record_ids=first.promoted_record_ids + second.promoted_record_ids,
        grounding_failures=first.grounding_failures + second.grounding_failures,
    )


def _extract_ground_promote(
    paper_ids: tuple[int, ...],
    *,
    evidence: Path,
    policy: GroundedCompletionPolicy,
    ke_executable: str,
    execution_budget: ExecutionBudget | None,
) -> _ExtractionResult:
    with tempfile.TemporaryDirectory(prefix="ke-gqr-grounded-extraction-") as scratch:
        root = Path(scratch)
        draft_path = root / "draft.jsonl"
        classified_path = root / "classified.jsonl"
        bounded_path = root / "bounded-classified.jsonl"
        staged_path = root / "staged-evidence.jsonl"
        ready_path = root / "ready-reviewed.jsonl"

        batch_command = [
            _resolve_ke_executable(ke_executable),
            "extraction-review-batch-generate",
            "--output",
            str(draft_path),
        ]
        for paper_id in paper_ids:
            batch_command.extend(("--paper-id", str(paper_id)))
        _run_checked(
            batch_command,
            operation="ke extraction-review-batch-generate",
            policy=policy,
            execution_budget=execution_budget,
        )
        draft_records = _read_jsonl(draft_path)

        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "extraction-review-autoclassify",
                "--input",
                str(draft_path),
                "--output",
                str(classified_path),
            ],
            operation="ke extraction-review-autoclassify",
            policy=policy,
            execution_budget=execution_budget,
        )
        classified_records = _read_jsonl(classified_path)
        bounded_records = classified_records[: policy.max_promoted_records]
        if not bounded_records:
            return _ExtractionResult(len(draft_records), 0, (), (), ())
        _write_jsonl(bounded_path, bounded_records)

        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "extraction-review-promote",
                "--input",
                str(bounded_path),
                "--output",
                str(staged_path),
            ],
            operation="ke extraction-review-promote (staging)",
            policy=policy,
            execution_budget=execution_budget,
        )
        staged_records = _read_jsonl(staged_path)
        staged_ids = _record_ids(staged_records)

        grounding_failures: list[str] = []
        try:
            _run_checked(
                [
                    _resolve_ke_executable(ke_executable),
                    "evidence-review-automate",
                    "--evidence",
                    str(staged_path),
                    "--model",
                    policy.grounding_model,
                    "--limit",
                    str(len(staged_ids)),
                ],
                operation="ke evidence-review-automate (batch)",
                policy=policy,
                execution_budget=execution_budget,
            )
        except KeCommandError:
            # Core's batch command preserves the exact same per-record grounding
            # rules. If the batch process itself fails, we cannot safely claim
            # which staged records completed, so retain the fail-closed signal
            # for every staged identity. The reviewed-file gate below still
            # determines what, if anything, is eligible for durable promotion.
            grounding_failures.extend(staged_ids)

        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "evidence-record-review-promote",
                "--evidence",
                str(staged_path),
            ],
            operation="ke evidence-record-review-promote",
            policy=policy,
            execution_budget=execution_budget,
        )
        reviewed_records = _read_jsonl(staged_path)
        ready_records = tuple(
            record for record in reviewed_records if _is_grounded_reviewed(record)
        )
        grounded_ids = _record_ids(ready_records)
        if not ready_records:
            return _ExtractionResult(
                len(draft_records),
                len(classified_records),
                staged_ids,
                (),
                (),
                tuple(grounding_failures),
            )

        _write_jsonl(ready_path, ready_records)
        before_ids = set(_evidence_ids(evidence))
        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "extraction-review-promote",
                "--input",
                str(ready_path),
                "--output",
                str(evidence),
            ],
            operation="ke extraction-review-promote (durable grounded evidence)",
            policy=policy,
            execution_budget=execution_budget,
        )
        promoted_ids = tuple(
            record_id for record_id in _evidence_ids(evidence) if record_id not in before_ids
        )
        return _ExtractionResult(
            len(draft_records),
            len(classified_records),
            staged_ids,
            grounded_ids,
            promoted_ids,
            tuple(grounding_failures),
        )


def _run_checked(
    command: list[str],
    *,
    operation: str,
    policy: GroundedCompletionPolicy,
    execution_budget: ExecutionBudget | None,
) -> None:
    try:
        result = _run_ke_command(
            command,
            operation=operation,
            execution_budget=execution_budget,
            working_directory=policy.core_working_directory,
        )
    except FileNotFoundError as exc:
        raise KeCommandError(
            f"Could not run {command[0]!r} -- is knowledge-engine-core installed and on PATH?"
        ) from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise KeCommandError(f"`{operation}` exited {result.returncode}: {message}")


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KeCommandError(f"Malformed JSONL at {path.name}:{line_number}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise KeCommandError(f"Malformed JSONL at {path.name}:{line_number}: expected object.")
        records.append(parsed)
    return tuple(records)


def _write_jsonl(path: Path, records: tuple[dict[str, Any], ...]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _record_ids(records: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        str(record["evidence_record_id"]) for record in records if record.get("evidence_record_id")
    )


def _is_grounded_reviewed(record: dict[str, Any]) -> bool:
    checklist = record.get("review_checklist")
    return (
        record.get("review_status") == "reviewed"
        and isinstance(checklist, dict)
        and checklist.get("llm_grounded") is True
    )


def _evidence_ids(path: Path) -> tuple[str, ...]:
    return _record_ids(_read_jsonl(path))


__all__ = [
    "DEFAULT_MIN_PROMOTED_RECORDS_FOR_EARLY_STOP",
    "AcquisitionRouteResult",
    "GroundedCompletionContractError",
    "GroundedCompletionPolicy",
    "GroundedCompletionPolicyError",
    "GroundedCompletionResult",
    "complete_discovered_research",
]


def _elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)
