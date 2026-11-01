"""An empty golden-question suite must not pass (Codex finding on PR #36)."""

from __future__ import annotations

from knowledge_engine_ai.retrieval_benchmark import GoldenQuestion, evaluate_retrieval
from knowledge_engine_ai.retrieval_benchmark_runner import (
    GoldenBenchmarkRun,
    GoldenBenchmarkSuite,
)


def _run(question_id: str, retrieved: tuple[str, ...]) -> GoldenBenchmarkRun:
    question = GoldenQuestion(
        question_id=question_id,
        domain="glp1",
        question="Does treatment help?",
        required_evidence_ids=("ev-a",),
        qualifier_evidence_ids=(),
    )
    return GoldenBenchmarkRun(question=question, result=evaluate_retrieval(question, retrieved))


def test_a_suite_that_ran_no_questions_does_not_pass() -> None:
    assert GoldenBenchmarkSuite(limit=10, runs=()).passes is False


def test_a_suite_whose_every_question_passes_still_passes() -> None:
    suite = GoldenBenchmarkSuite(limit=10, runs=(_run("q1", ("ev-a",)), _run("q2", ("ev-a",))))

    assert suite.passes is True


def test_one_failing_question_fails_the_suite() -> None:
    suite = GoldenBenchmarkSuite(limit=10, runs=(_run("q1", ("ev-a",)), _run("q2", ())))

    assert suite.passes is False
