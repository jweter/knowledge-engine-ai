from __future__ import annotations

import pytest

from knowledge_engine_ai.retrieval_benchmark import (
    GoldenQuestion,
    default_golden_questions,
    evaluate_retrieval,
)


def test_default_bank_is_cross_domain_and_uses_reviewed_expectations() -> None:
    questions = default_golden_questions()

    assert [question.domain for question in questions] == [
        "glp1",
        "oncology",
        "mental_health",
    ]
    assert all(question.required_evidence_ids for question in questions)
    assert all(
        set(question.qualifier_evidence_ids) <= set(question.required_evidence_ids)
        for question in questions
    )


def test_evaluate_retrieval_reports_required_and_qualifier_recall() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="test",
        question="Does the intervention help?",
        required_evidence_ids=("ev-a", "ev-b", "ev-c"),
        qualifier_evidence_ids=("ev-c",),
    )

    result = evaluate_retrieval(question, ("ev-x", "ev-a", "ev-c"), k=3)

    assert result.required_found == ("ev-a", "ev-c")
    assert result.required_missing == ("ev-b",)
    assert result.qualifier_found == ("ev-c",)
    assert result.qualifier_missing == ()
    assert result.recall_at_k == pytest.approx(2 / 3)
    assert result.qualifier_recall_at_k == 1.0
    assert result.passes_required_recall is False
    assert result.passes_qualifier_recall is True
    assert result.passes is False


def test_evaluate_retrieval_applies_rank_cutoff_before_scoring() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="test",
        question="Does the intervention help?",
        required_evidence_ids=("ev-a", "ev-b"),
    )

    result = evaluate_retrieval(question, ("ev-a", "ev-x", "ev-b"), k=2)

    assert result.retrieved_evidence_ids == ("ev-a", "ev-x")
    assert result.required_missing == ("ev-b",)
    assert result.recall_at_k == 0.5
    assert result.qualifier_recall_at_k is None


def test_evaluate_retrieval_deduplicates_ranked_ids_without_inflating_recall() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="test",
        question="Does the intervention help?",
        required_evidence_ids=("ev-a", "ev-b"),
    )

    result = evaluate_retrieval(question, ("ev-a", "ev-a", "ev-b"))

    assert result.retrieved_evidence_ids == ("ev-a", "ev-b")
    assert result.recall_at_k == 1.0
    assert result.passes is True


def test_golden_question_rejects_qualifier_not_in_required_set() -> None:
    with pytest.raises(ValueError, match="must also be required"):
        GoldenQuestion(
            question_id="q1",
            domain="test",
            question="Does the intervention help?",
            required_evidence_ids=("ev-a",),
            qualifier_evidence_ids=("ev-b",),
        )


def test_evaluate_retrieval_rejects_nonpositive_k() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="test",
        question="Does the intervention help?",
        required_evidence_ids=("ev-a",),
    )

    with pytest.raises(ValueError, match="k must be positive"):
        evaluate_retrieval(question, ("ev-a",), k=0)
