"""GQR-4/GQR-5 bridge from acquisition plans to grounded re-retrieval.

This module closes the first executable path between Core's persisted discovery
candidates and an EvidenceReport that may be used for synthesis. It deliberately
composes Core's existing public ``ke`` commands instead of importing Core as a
Python package:

acquisition plan -> bounded route execution -> persisted Papers -> extraction
review queue -> automated classification -> staged EvidenceRecords -> LLM-grounded
PICO verification -> automated review promotion -> Core-validated append to the
real evidence store -> original-question re-retrieval.

The staging step is the trust boundary. Raw automatically classified records are
never appended to the caller's evidence file. They are first promoted into a
private temporary evidence file, passed through Core's grounding verifier and
``evidence-record-review-promote`` gate, and only records that are both
``llm_grounded`` and ``reviewed`` are submitted to Core's promotion validator for
final persistence. Discovery candidates and merely acquired Papers therefore
never become synthesis inputs by shortcut.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.execution import ExecutionBudget
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


class GroundedCompletionPolicyError(ValueError):
    """A grounded-completion policy contains an unsafe or unbounded value."""


class GroundedCompletionContractError(RuntimeError):
    """Core returned a receipt that cannot be reconciled to the requested route."""


@dataclass(frozen=True)
class GroundedCompletionPolicy:
    """Explicit bounds and filesystem context for one GQR-4/GQR-5 completion pass."""

    papers_dir: Path
    grounding_model: str
    core_working_directory: Path | None = None
    max_acquisition_routes: int = 4
    max_candidates_per_route: int = 10
    max_full_text_acquisitions_per_route: int = 5
    max_elapsed_seconds_per_route: int = 120
    max_promoted_records: int = 12
    reretrieval_limit: int = 5

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


@dataclass(frozen=True)
class AcquisitionRouteResult:
    """One acquisition route's durable outcome."""

    route: str
    candidate_ids: tuple[str, ...]
    attempted: bool
    paper_ids: tuple[int, ...] = ()
    import_run_id: str | None = None
    persisted_count: int = 0
    reused_count: int = 0
    error: str | None = None

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
        }


@dataclass(frozen=True)
class GroundedCompletionResult:
    """Structured GQR-4/GQR-5 completion outcome for one discovery augmentation."""

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
    skipped_reason: str | None = None

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
            "completed_with_new_evidence": self.completed_with_new_evidence,
            "skipped_reason": self.skipped_reason,
        }


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

    The function never turns provider candidates directly into evidence. Core owns
    every durable acquisition and EvidenceRecord promotion operation. Individual
    acquisition-route failures degrade the run but do not erase successful routes.
    Extraction/promotion failure stops the new-evidence path before re-retrieval so
    an ungrounded staged record can never enter synthesis accidentally.
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
            skipped_reason=discovery.acquisition_plan_skipped_reason
            or discovery.acquisition_plan_error
            or "no acquisition plan available",
        )

    already_indexed = tuple(
        sorted(
            {
                item.existing_paper_id
                for item in plan.items
                if item.disposition == _ALREADY_INDEXED and item.existing_paper_id is not None
            }
        )
    )
    route_candidates = _route_candidates(plan)
    route_results: list[AcquisitionRouteResult] = []
    acquired_paper_ids: list[int] = []

    for route, candidate_ids in route_candidates[: policy.max_acquisition_routes]:
        try:
            route_result = _execute_acquisition_route(
                plan,
                route=route,
                candidate_ids=candidate_ids,
                policy=policy,
                ke_executable=ke_executable,
                execution_budget=execution_budget,
            )
        except (KeCommandError, GroundedCompletionContractError) as exc:
            route_result = AcquisitionRouteResult(
                route=route,
                candidate_ids=candidate_ids,
                attempted=True,
                error=str(exc),
            )
        route_results.append(route_result)
        acquired_paper_ids.extend(route_result.paper_ids)

    paper_ids = tuple(dict.fromkeys((*already_indexed, *acquired_paper_ids)))
    if not paper_ids:
        return GroundedCompletionResult(
            attempted=True,
            search_run_id=plan.search_run_id,
            research_question_id=plan.research_question_id,
            already_indexed_paper_ids=already_indexed,
            acquisition_routes=tuple(route_results),
            skipped_reason="no persisted or reusable paper was available for grounded extraction",
        )

    try:
        extraction = _extract_ground_promote(
            paper_ids,
            evidence=evidence,
            policy=policy,
            ke_executable=ke_executable,
            execution_budget=execution_budget,
        )
    except KeCommandError as exc:
        return GroundedCompletionResult(
            attempted=True,
            search_run_id=plan.search_run_id,
            research_question_id=plan.research_question_id,
            already_indexed_paper_ids=already_indexed,
            acquisition_routes=tuple(route_results),
            paper_ids=paper_ids,
            extraction_error=str(exc),
        )

    promoted_ids = extraction.promoted_record_ids
    reretrieval: EvidenceReport | None = None
    reretrieval_error: str | None = None
    if promoted_ids:
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
        promoted_record_ids=promoted_ids,
        grounding_failures=extraction.grounding_failures,
        reretrieval_report=reretrieval,
        reretrieval_error=reretrieval_error,
        skipped_reason=(
            "no automatically classified record passed grounded review"
            if not promoted_ids and extraction.extraction_error is None
            else None
        ),
    )


@dataclass(frozen=True)
class _ExtractionResult:
    draft_item_count: int
    classified_item_count: int
    staged_record_ids: tuple[str, ...]
    grounded_record_ids: tuple[str, ...]
    promoted_record_ids: tuple[str, ...]
    grounding_failures: tuple[str, ...] = field(default_factory=tuple)
    extraction_error: str | None = None


def _route_candidates(
    plan: GeneralQuestionAcquisitionPlanResult,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    grouped: dict[str, list[str]] = {}
    for item in plan.items:
        if item.disposition != _ELIGIBLE_FULL_TEXT or item.acquisition_route is None:
            continue
        if item.acquisition_route not in _ROUTE_COMMANDS:
            continue
        grouped.setdefault(item.acquisition_route, []).append(item.candidate_id)
    return tuple(
        (route, tuple(grouped[route])) for route in _ROUTE_COMMANDS if route in grouped
    )


def _execute_acquisition_route(
    plan: GeneralQuestionAcquisitionPlanResult,
    *,
    route: str,
    candidate_ids: tuple[str, ...],
    policy: GroundedCompletionPolicy,
    ke_executable: str,
    execution_budget: ExecutionBudget | None,
) -> AcquisitionRouteResult:
    command_name = _ROUTE_COMMANDS[route]
    bounded_candidate_ids = candidate_ids[: policy.max_candidates_per_route]
    request_payload = {
        "schema_version": 1,
        "search_run_id": plan.search_run_id,
        "research_question_id": plan.research_question_id,
        "candidate_ids": list(bounded_candidate_ids),
        "max_candidates": len(bounded_candidate_ids),
        "max_full_text_acquisitions": min(
            len(bounded_candidate_ids), policy.max_full_text_acquisitions_per_route
        ),
        "max_elapsed_seconds": policy.max_elapsed_seconds_per_route,
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
            str(plan_ledger_root := _require_ledger_root_from_policy(policy)),
            "--papers-dir",
            str(policy.papers_dir),
            "--receipt",
            str(receipt_path),
        ]
        try:
            completed = _run_ke_command(
                command,
                operation=f"ke {command_name}",
                execution_budget=execution_budget,
                working_directory=policy.core_working_directory,
            )
        except FileNotFoundError as exc:
            raise KeCommandError(
                f"Could not run {ke_executable!r} -- is knowledge-engine-core installed and on PATH?"
            ) from exc
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise KeCommandError(f"`ke {command_name}` exited {completed.returncode}: {message}")
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(f"`ke {command_name}` did not write a readable receipt: {exc}") from exc

    _ = plan_ledger_root  # retained in the command above for explicit provenance readability.
    return _parse_acquisition_receipt(
        payload,
        route=route,
        candidate_ids=bounded_candidate_ids,
        search_run_id=plan.search_run_id,
        research_question_id=plan.research_question_id,
    )


def _require_ledger_root_from_policy(policy: GroundedCompletionPolicy) -> Path:
    # Core's acquisition executor must read the exact federated run ledger. The
    # completion policy intentionally derives it from the Core working directory
    # only when the caller has configured the conventional location; callers that
    # need a different location should pass an absolute papers/core root layout.
    if policy.core_working_directory is None:
        raise GroundedCompletionPolicyError(
            "core_working_directory is required for acquisition execution so the "
            "federated ledger can be resolved deterministically."
        )
    return policy.core_working_directory / "data" / "federated_search_runs"


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
        received_candidate_ids = tuple(item["candidate_id"] for item in items)
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
        staged_evidence_path = root / "staged-evidence.jsonl"
        ready_path = root / "ready-reviewed.jsonl"

        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "extraction-review-batch-generate",
                "--output",
                str(draft_path),
                *[argument for paper_id in paper_ids for argument in ("--paper-id", str(paper_id))],
            ],
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
            return _ExtractionResult(
                draft_item_count=len(draft_records),
                classified_item_count=0,
                staged_record_ids=(),
                grounded_record_ids=(),
                promoted_record_ids=(),
            )
        _write_jsonl(bounded_path, bounded_records)

        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "extraction-review-promote",
                "--input",
                str(bounded_path),
                "--output",
                str(staged_evidence_path),
            ],
            operation="ke extraction-review-promote (staging)",
            policy=policy,
            execution_budget=execution_budget,
        )
        staged_records = _read_jsonl(staged_evidence_path)
        staged_ids = tuple(
            str(record["evidence_record_id"])
            for record in staged_records
            if record.get("evidence_record_id")
        )

        grounding_failures: list[str] = []
        for evidence_record_id in staged_ids:
            try:
                _run_checked(
                    [
                        _resolve_ke_executable(ke_executable),
                        "evidence-review-automate",
                        "--evidence",
                        str(staged_evidence_path),
                        "--model",
                        policy.grounding_model,
                        "--evidence-record-id",
                        evidence_record_id,
                    ],
                    operation=f"ke evidence-review-automate {evidence_record_id}",
                    policy=policy,
                    execution_budget=execution_budget,
                )
            except KeCommandError:
                grounding_failures.append(evidence_record_id)

        _run_checked(
            [
                _resolve_ke_executable(ke_executable),
                "evidence-record-review-promote",
                "--evidence",
                str(staged_evidence_path),
            ],
            operation="ke evidence-record-review-promote",
            policy=policy,
            execution_budget=execution_budget,
        )
        reviewed_records = _read_jsonl(staged_evidence_path)
        ready_records = tuple(record for record in reviewed_records if _is_grounded_reviewed(record))
        grounded_ids = tuple(str(record["evidence_record_id"]) for record in ready_records)
        if not ready_records:
            return _ExtractionResult(
                draft_item_count=len(draft_records),
                classified_item_count=len(classified_records),
                staged_record_ids=staged_ids,
                grounded_record_ids=(),
                promoted_record_ids=(),
                grounding_failures=tuple(grounding_failures),
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
        after_ids = _evidence_ids(evidence)
        promoted_ids = tuple(record_id for record_id in after_ids if record_id not in before_ids)

        return _ExtractionResult(
            draft_item_count=len(draft_records),
            classified_item_count=len(classified_records),
            staged_record_ids=staged_ids,
            grounded_record_ids=grounded_ids,
            promoted_record_ids=promoted_ids,
            grounding_failures=tuple(grounding_failures),
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


def _is_grounded_reviewed(record: dict[str, Any]) -> bool:
    checklist = record.get("review_checklist")
    return (
        record.get("review_status") == "reviewed"
        and isinstance(checklist, dict)
        and checklist.get("llm_grounded") is True
    )


def _evidence_ids(path: Path) -> tuple[str, ...]:
    return tuple(
        str(record["evidence_record_id"])
        for record in _read_jsonl(path)
        if record.get("evidence_record_id")
    )


__all__ = [
    "AcquisitionRouteResult",
    "GroundedCompletionContractError",
    "GroundedCompletionPolicy",
    "GroundedCompletionPolicyError",
    "GroundedCompletionResult",
    "complete_discovered_research",
]
