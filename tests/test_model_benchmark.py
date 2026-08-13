from __future__ import annotations

from knowledge_engine_ai.copilot.intent import PrivacyClass
from knowledge_engine_ai.model_benchmark import (
    BenchmarkOutcome,
    BenchmarkTask,
    ModelBenchmarkResult,
    ModelCandidate,
    provider_specs_from_benchmark,
    recommend_models_by_role,
    run_model_benchmark,
)
from knowledge_engine_ai.routing import ModelRole


class _FakeLLM:
    def __init__(self, name: str) -> None:
        self.name = name

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del prompt, max_tokens, timeout_seconds
        return self.name


def _always_pass(_: object) -> BenchmarkOutcome:
    return BenchmarkOutcome(passed=True, detail="ok")


def _always_fail(_: object) -> BenchmarkOutcome:
    return BenchmarkOutcome(passed=False, detail="never grounds")


def _raises(_: object) -> BenchmarkOutcome:
    raise RuntimeError("model transport exploded")


def test_run_model_benchmark_records_a_result_per_model_per_task() -> None:
    candidates = (ModelCandidate("small", 1.5), ModelCandidate("large", 4.0))
    tasks = (BenchmarkTask("planning", ModelRole.REASONER, _always_pass),)

    results = run_model_benchmark(candidates, tasks, llm_factory=_FakeLLM)

    assert len(results) == 2
    assert {result.model_tag for result in results} == {"small", "large"}
    assert all(result.outcome.passed for result in results)


def test_run_model_benchmark_turns_a_raised_exception_into_a_failed_outcome() -> None:
    candidates = (ModelCandidate("flaky", 1.5),)
    tasks = (BenchmarkTask("planning", ModelRole.REASONER, _raises),)

    results = run_model_benchmark(candidates, tasks, llm_factory=_FakeLLM)

    assert len(results) == 1
    assert results[0].outcome.passed is False
    assert "model transport exploded" in results[0].outcome.detail


def test_recommend_models_by_role_picks_the_smallest_qualifying_candidate() -> None:
    results = (
        ModelBenchmarkResult(
            "small", "synthesis", ModelRole.SYNTHESIS, BenchmarkOutcome(True, "ok")
        ),
        ModelBenchmarkResult(
            "large", "synthesis", ModelRole.SYNTHESIS, BenchmarkOutcome(True, "ok")
        ),
    )
    candidates = (ModelCandidate("small", 1.5), ModelCandidate("large", 4.0))

    recommendation = recommend_models_by_role(candidates, results)

    assert recommendation == {ModelRole.SYNTHESIS: "small"}


def test_recommend_models_by_role_skips_a_disqualified_smaller_candidate() -> None:
    results = (
        ModelBenchmarkResult(
            "small", "synthesis", ModelRole.SYNTHESIS, BenchmarkOutcome(False, "hallucinated")
        ),
        ModelBenchmarkResult(
            "large", "synthesis", ModelRole.SYNTHESIS, BenchmarkOutcome(True, "ok")
        ),
    )
    candidates = (ModelCandidate("small", 1.5), ModelCandidate("large", 4.0))

    recommendation = recommend_models_by_role(candidates, results)

    assert recommendation == {ModelRole.SYNTHESIS: "large"}


def test_a_role_with_zero_qualifying_candidates_is_omitted_not_an_error() -> None:
    results = (
        ModelBenchmarkResult(
            "small", "planning", ModelRole.REASONER, BenchmarkOutcome(False, "bad json")
        ),
    )
    candidates = (ModelCandidate("small", 1.5),)

    recommendation = recommend_models_by_role(candidates, results)

    assert recommendation == {}


def test_a_candidate_must_pass_every_task_for_its_role_to_qualify() -> None:
    results = (
        ModelBenchmarkResult("small", "planning", ModelRole.REASONER, BenchmarkOutcome(True, "ok")),
        ModelBenchmarkResult(
            "small", "reasoning_depth", ModelRole.REASONER, BenchmarkOutcome(False, "shallow")
        ),
        ModelBenchmarkResult("large", "planning", ModelRole.REASONER, BenchmarkOutcome(True, "ok")),
        ModelBenchmarkResult(
            "large", "reasoning_depth", ModelRole.REASONER, BenchmarkOutcome(True, "ok")
        ),
    )
    candidates = (ModelCandidate("small", 1.5), ModelCandidate("large", 4.0))

    recommendation = recommend_models_by_role(candidates, results)

    assert recommendation == {ModelRole.REASONER: "large"}


def test_ties_break_by_tag() -> None:
    results = (
        ModelBenchmarkResult(
            "model-b", "planning", ModelRole.REASONER, BenchmarkOutcome(True, "ok")
        ),
        ModelBenchmarkResult(
            "model-a", "planning", ModelRole.REASONER, BenchmarkOutcome(True, "ok")
        ),
    )
    candidates = (ModelCandidate("model-b", 1.5), ModelCandidate("model-a", 1.5))

    recommendation = recommend_models_by_role(candidates, results)

    assert recommendation == {ModelRole.REASONER: "model-a"}


def test_provider_specs_from_benchmark_produces_one_local_spec_per_role() -> None:
    recommendation = {ModelRole.SYNTHESIS: "small", ModelRole.REASONER: "large"}

    specs = provider_specs_from_benchmark(recommendation)

    assert len(specs) == 2
    by_role = {next(iter(spec.roles)): spec for spec in specs}
    assert by_role[ModelRole.SYNTHESIS].local is True
    assert by_role[ModelRole.SYNTHESIS].provider_id == "benchmarked:small"
    assert by_role[ModelRole.SYNTHESIS].max_privacy is PrivacyClass.SENSITIVE


def test_provider_specs_from_benchmark_never_defaults_to_secret_privacy() -> None:
    specs = provider_specs_from_benchmark({ModelRole.ROUTINE: "small"})

    assert all(spec.max_privacy is not PrivacyClass.SECRET for spec in specs)
