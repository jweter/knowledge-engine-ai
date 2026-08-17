from __future__ import annotations

import pytest

from knowledge_engine_ai.retrieval_baseline_compare import compare_baselines


def _snapshot(
    *,
    recall: float,
    qualifier_recall: float,
    question: str = "Does treatment help?",
    limit: int = 10,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "core_commit": "core123",
        "ai_commit": "ai123",
        "retrieval_limit": limit,
        "passes": True,
        "runs": [
            {
                "question_id": "q1",
                "domain": "glp1",
                "question": question,
                "required_evidence_ids": ["ev-a", "ev-b"],
                "qualifier_evidence_ids": ["ev-b"],
                "result": {
                    "recall_at_k": recall,
                    "qualifier_recall_at_k": qualifier_recall,
                },
            }
        ],
    }


def test_compare_baselines_detects_improvement_without_regression() -> None:
    comparison = compare_baselines(
        _snapshot(recall=0.5, qualifier_recall=0.0),
        _snapshot(recall=1.0, qualifier_recall=1.0),
    )

    assert comparison["regression_count"] == 0
    assert comparison["improvement_count"] == 1
    assert comparison["passes_regression_gate"] is True
    question = comparison["questions"][0]
    assert question["recall_delta"] == 0.5
    assert question["qualifier_recall_delta"] == 1.0
    assert question["improved"] is True


def test_compare_baselines_flags_qualifier_regression() -> None:
    comparison = compare_baselines(
        _snapshot(recall=1.0, qualifier_recall=1.0),
        _snapshot(recall=1.0, qualifier_recall=0.0),
    )

    assert comparison["regression_count"] == 1
    assert comparison["passes_regression_gate"] is False
    assert comparison["questions"][0]["regressed"] is True


def test_compare_baselines_rejects_different_limits() -> None:
    with pytest.raises(ValueError, match="same retrieval_limit"):
        compare_baselines(
            _snapshot(recall=1.0, qualifier_recall=1.0, limit=10),
            _snapshot(recall=1.0, qualifier_recall=1.0, limit=20),
        )


def test_compare_baselines_rejects_changed_golden_question_definition() -> None:
    with pytest.raises(ValueError, match="definition changed"):
        compare_baselines(
            _snapshot(recall=1.0, qualifier_recall=1.0),
            _snapshot(
                recall=1.0,
                qualifier_recall=1.0,
                question="Did the golden question change?",
            ),
        )


def test_compare_baselines_rejects_unsupported_schema() -> None:
    reference = _snapshot(recall=1.0, qualifier_recall=1.0)
    reference["schema_version"] = 2

    with pytest.raises(ValueError, match="schema_version"):
        compare_baselines(reference, _snapshot(recall=1.0, qualifier_recall=1.0))
