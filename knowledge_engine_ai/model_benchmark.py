"""AI-O8: benchmark local models, recommend the smallest one that clears the bar.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O8 milestone: "Benchmark
local models on planning, extraction, evidence comparison, synthesis, and
citation compliance. Success criterion: use the smallest model meeting
task-quality thresholds." See `docs/ai_o8_design.md` for the full plan
this module implements.

Every task probe here reuses an already-tested deterministic grader this
project already has -- AI-O1's `validate_research_plan` (via AI-O4's
`plan_from_question`) and AI-O6's `verify_synthesis` -- rather than
inventing a new scoring method. `provider_specs_from_benchmark` closes the
loop into `routing.py`'s already-merged `select_provider`: a benchmark
recommendation becomes better-informed input to that one routing
mechanism, not a second one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from knowledge_engine_ai.copilot.intent import PrivacyClass
from knowledge_engine_ai.llm import LocalLLM
from knowledge_engine_ai.routing import ModelRole, ProviderSpec


@dataclass(frozen=True)
class ModelCandidate:
    """One locally-pulled model, with a caller-supplied approximate size.

    `approx_parameter_count_billions` is typed in by the caller (e.g.
    read off `ollama list`'s own output) rather than auto-detected --
    this project cannot reliably infer a pulled model's true parameter
    count from Ollama's API without depending on tag-naming conventions
    that are not guaranteed stable across model families.
    """

    tag: str
    approx_parameter_count_billions: float


@dataclass(frozen=True)
class BenchmarkOutcome:
    """One task probe's pass/fail result against one model."""

    passed: bool
    detail: str


@dataclass(frozen=True)
class BenchmarkTask:
    """A named, role-tagged probe: given a model, return a pass/fail outcome."""

    name: str
    role: ModelRole
    run: Callable[[LocalLLM], BenchmarkOutcome]


@dataclass(frozen=True)
class ModelBenchmarkResult:
    """One (model, task) pairing's outcome."""

    model_tag: str
    task_name: str
    role: ModelRole
    outcome: BenchmarkOutcome


def run_model_benchmark(
    candidates: tuple[ModelCandidate, ...],
    tasks: tuple[BenchmarkTask, ...],
    llm_factory: Callable[[str], LocalLLM],
) -> tuple[ModelBenchmarkResult, ...]:
    """Run every task against every candidate model.

    One candidate's crash (model not pulled, transport timeout, any
    unexpected exception inside a task's `run`) never stops the rest of
    the sweep -- it is recorded as a failed `BenchmarkOutcome` with the
    exception's message as `detail`, the same "one step's failure does
    not stop the rest" discipline `run_fixed_evidence_workflow` and
    `run_parallel_retrieval` already follow for a workflow, applied here
    to a benchmark sweep.
    """

    results: list[ModelBenchmarkResult] = []
    for candidate in candidates:
        llm = llm_factory(candidate.tag)
        for task in tasks:
            try:
                outcome = task.run(llm)
            except Exception as exc:  # noqa: BLE001 - a benchmark records failures, it does not crash on one.
                outcome = BenchmarkOutcome(passed=False, detail=f"{type(exc).__name__}: {exc}")
            results.append(
                ModelBenchmarkResult(
                    model_tag=candidate.tag,
                    task_name=task.name,
                    role=task.role,
                    outcome=outcome,
                )
            )
    return tuple(results)


def recommend_models_by_role(
    candidates: tuple[ModelCandidate, ...],
    results: tuple[ModelBenchmarkResult, ...],
) -> dict[ModelRole, str]:
    """Recommend the smallest candidate that passed every task for each role.

    A role with zero qualifying candidates is simply omitted from the
    returned mapping -- "nothing pulled locally clears this bar yet" is
    itself a meaningful, reportable result, not an error condition.
    Ties broken by `tag`, matching `routing.select_provider`'s own
    tie-break for reproducibility.
    """

    size_by_tag = {
        candidate.tag: candidate.approx_parameter_count_billions for candidate in candidates
    }

    roles = {result.role for result in results}
    recommendation: dict[ModelRole, str] = {}
    for role in roles:
        role_results = [result for result in results if result.role is role]
        tags_in_role = {result.model_tag for result in role_results}

        qualifying: list[str] = []
        for tag in tags_in_role:
            tag_results = [result for result in role_results if result.model_tag == tag]
            if all(result.outcome.passed for result in tag_results):
                qualifying.append(tag)

        if not qualifying:
            continue

        qualifying.sort(key=lambda tag: (size_by_tag[tag], tag))
        recommendation[role] = qualifying[0]

    return recommendation


def provider_specs_from_benchmark(
    recommendation: dict[ModelRole, str],
    *,
    max_privacy: PrivacyClass = PrivacyClass.SENSITIVE,
    priority: int = 10,
) -> tuple[ProviderSpec, ...]:
    """Turn a benchmark recommendation into `ProviderSpec`s `select_provider` can rank.

    Every candidate this module benchmarks is a local Ollama model, so
    each resulting `ProviderSpec` is `local=True`. `max_privacy` defaults
    to `SENSITIVE`, never `SECRET` -- matching `routing.py`'s own
    invariant that SECRET-class data must never reach model context,
    benchmarked or not.
    """

    return tuple(
        ProviderSpec(
            provider_id=f"benchmarked:{model_tag}",
            roles=frozenset({role}),
            local=True,
            max_privacy=max_privacy,
            priority=priority,
        )
        for role, model_tag in recommendation.items()
    )


__all__ = [
    "BenchmarkOutcome",
    "BenchmarkTask",
    "ModelBenchmarkResult",
    "ModelCandidate",
    "provider_specs_from_benchmark",
    "recommend_models_by_role",
    "run_model_benchmark",
]
