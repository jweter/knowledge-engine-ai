"""Deterministic comparison of reproducible retrieval baseline snapshots."""

from __future__ import annotations

from typing import Any


def _runs_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported retrieval baseline schema_version.")
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise ValueError("Retrieval baseline snapshot must contain a runs list.")

    indexed: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("Each retrieval baseline run must be an object.")
        question_id = run.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("Each retrieval baseline run must have a question_id.")
        if question_id in indexed:
            raise ValueError(f"Duplicate retrieval baseline question_id: {question_id}")
        indexed[question_id] = run
    return indexed


def _question_definition(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run.get("domain"),
        run.get("question"),
        run.get("required_evidence_ids"),
        run.get("qualifier_evidence_ids"),
    )


def _metric(run: dict[str, Any], name: str) -> float:
    result = run.get("result")
    if not isinstance(result, dict):
        raise ValueError("Each retrieval baseline run must contain a result object.")
    value = result.get(name)
    if not isinstance(value, int | float):
        raise ValueError(f"Retrieval baseline result is missing numeric {name}.")
    return float(value)


def compare_baselines(
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Compare two compatible baseline snapshots and identify ranking regressions."""

    reference_runs = _runs_by_id(reference)
    candidate_runs = _runs_by_id(candidate)

    if reference.get("retrieval_limit") != candidate.get("retrieval_limit"):
        raise ValueError("Retrieval baseline snapshots must use the same retrieval_limit.")
    if set(reference_runs) != set(candidate_runs):
        raise ValueError("Retrieval baseline snapshots must contain the same golden questions.")

    comparisons: list[dict[str, Any]] = []
    regression_count = 0
    improvement_count = 0

    for question_id in sorted(reference_runs):
        reference_run = reference_runs[question_id]
        candidate_run = candidate_runs[question_id]
        if _question_definition(reference_run) != _question_definition(candidate_run):
            raise ValueError(
                f"Golden question definition changed for question_id {question_id!r}; "
                "compare only like-for-like snapshots."
            )

        reference_recall = _metric(reference_run, "recall_at_k")
        candidate_recall = _metric(candidate_run, "recall_at_k")
        reference_qualifier = _metric(reference_run, "qualifier_recall_at_k")
        candidate_qualifier = _metric(candidate_run, "qualifier_recall_at_k")
        recall_delta = candidate_recall - reference_recall
        qualifier_delta = candidate_qualifier - reference_qualifier
        regressed = recall_delta < 0 or qualifier_delta < 0
        improved = recall_delta > 0 or qualifier_delta > 0
        regression_count += int(regressed)
        improvement_count += int(improved)

        comparisons.append(
            {
                "question_id": question_id,
                "domain": reference_run.get("domain"),
                "reference_recall_at_k": reference_recall,
                "candidate_recall_at_k": candidate_recall,
                "recall_delta": recall_delta,
                "reference_qualifier_recall_at_k": reference_qualifier,
                "candidate_qualifier_recall_at_k": candidate_qualifier,
                "qualifier_recall_delta": qualifier_delta,
                "regressed": regressed,
                "improved": improved,
            }
        )

    return {
        "schema_version": 1,
        "reference_core_commit": reference.get("core_commit"),
        "reference_ai_commit": reference.get("ai_commit"),
        "candidate_core_commit": candidate.get("core_commit"),
        "candidate_ai_commit": candidate.get("ai_commit"),
        "retrieval_limit": reference.get("retrieval_limit"),
        "regression_count": regression_count,
        "improvement_count": improvement_count,
        "passes_regression_gate": regression_count == 0,
        "questions": comparisons,
    }
