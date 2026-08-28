"""Repeatable end-to-end benchmark projection for General Question Research Loop runs.

The benchmark deliberately consumes the same structured result returned by
``run_research_question``. It does not invent scientific scores or treat discovery
leads as evidence. Its job is engineering observability: record how a question moved
through the pipeline, how much useful material survived each stage, how long the run
took, and whether a repeated run reused prior work.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import GroundedCompletionResult
from knowledge_engine_ai.copilot.research_state import ResearchStateResult, derive_research_state
from knowledge_engine_ai.orchestrator.bottleneck_report import (
    ResearchPipelineStage,
    SessionBottleneckReport,
    build_session_bottleneck_report,
)
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.observability import SessionTrace
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult

BENCHMARK_SCHEMA_VERSION = 1


class BenchmarkResearchResult(Protocol):
    """Minimal completed research-result surface needed by the benchmark."""

    @property
    def session_id(self) -> str: ...

    @property
    def question(self) -> str: ...

    @property
    def workflow(self) -> WorkflowResult: ...

    @property
    def discovery(self) -> DiscoveryAugmentationResult | None: ...

    @property
    def grounded_completion(self) -> GroundedCompletionResult | None: ...

    @property
    def close_result(self) -> SessionCloseResult: ...

    @property
    def trace(self) -> SessionTrace: ...

    @property
    def narrative_releaseable(self) -> bool: ...

    @property
    def used_reretrieved_evidence(self) -> bool: ...


@dataclass(frozen=True)
class ResearchConversionFunnel:
    """Observed question-to-grounded-evidence conversion counts for one run."""

    indexed_evidence_record_count: int
    provider_attempt_count: int
    provider_degraded_count: int
    provider_outcomes: tuple[tuple[str, int], ...]
    discovery_candidate_count: int
    acquisition_plan_item_count: int
    acquisition_dispositions: tuple[tuple[str, int], ...]
    already_indexed_candidate_count: int
    eligible_full_text_candidate_count: int
    acquisition_route_attempt_count: int
    acquisition_candidate_attempt_count: int
    persisted_paper_count: int
    reused_paper_count: int
    available_paper_count: int
    draft_item_count: int
    classified_item_count: int
    staged_record_count: int
    grounded_record_count: int
    promoted_evidence_record_count: int
    grounding_failure_count: int
    reretrieval_attempt_count: int
    primary_indexed_retrieval_cache_hit: bool
    contradiction_indexed_retrieval_cache_hit: bool
    reuse_hit: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "indexed_evidence_record_count": self.indexed_evidence_record_count,
            "provider_attempt_count": self.provider_attempt_count,
            "provider_degraded_count": self.provider_degraded_count,
            "provider_outcomes": dict(self.provider_outcomes),
            "discovery_candidate_count": self.discovery_candidate_count,
            "acquisition_plan_item_count": self.acquisition_plan_item_count,
            "acquisition_dispositions": dict(self.acquisition_dispositions),
            "already_indexed_candidate_count": self.already_indexed_candidate_count,
            "eligible_full_text_candidate_count": self.eligible_full_text_candidate_count,
            "acquisition_route_attempt_count": self.acquisition_route_attempt_count,
            "acquisition_candidate_attempt_count": self.acquisition_candidate_attempt_count,
            "persisted_paper_count": self.persisted_paper_count,
            "reused_paper_count": self.reused_paper_count,
            "available_paper_count": self.available_paper_count,
            "draft_item_count": self.draft_item_count,
            "classified_item_count": self.classified_item_count,
            "staged_record_count": self.staged_record_count,
            "grounded_record_count": self.grounded_record_count,
            "promoted_evidence_record_count": self.promoted_evidence_record_count,
            "grounding_failure_count": self.grounding_failure_count,
            "reretrieval_attempt_count": self.reretrieval_attempt_count,
            "primary_indexed_retrieval_cache_hit": self.primary_indexed_retrieval_cache_hit,
            "contradiction_indexed_retrieval_cache_hit": (
                self.contradiction_indexed_retrieval_cache_hit
            ),
            "reuse_hit": self.reuse_hit,
        }


@dataclass(frozen=True)
class ResearchBenchmarkRun:
    """One cold or warm execution of a benchmark scenario."""

    schema_version: int
    scenario_id: str
    run_number: int
    run_temperature: str
    question: str
    question_fingerprint: str
    session_id: str
    evidence_store_revision: str | None
    wall_clock_duration_ms: int
    known_time_to_first_grounded_information_ms: int | None
    final_state: ResearchStateResult
    narrative_releaseable: bool
    used_reretrieved_evidence: bool
    funnel: ResearchConversionFunnel
    bottleneck_report: SessionBottleneckReport

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "run_number": self.run_number,
            "run_temperature": self.run_temperature,
            "question": self.question,
            "question_fingerprint": self.question_fingerprint,
            "session_id": self.session_id,
            "evidence_store_revision": self.evidence_store_revision,
            "wall_clock_duration_ms": self.wall_clock_duration_ms,
            "known_time_to_first_grounded_information_ms": (
                self.known_time_to_first_grounded_information_ms
            ),
            "final_state": self.final_state.to_dict(),
            "narrative_releaseable": self.narrative_releaseable,
            "used_reretrieved_evidence": self.used_reretrieved_evidence,
            "funnel": self.funnel.to_dict(),
            "bottleneck_report": self.bottleneck_report.to_dict(),
        }


@dataclass(frozen=True)
class ResearchBenchmarkSuite:
    """Repeated benchmark executions for the same question and mutable evidence store."""

    schema_version: int
    scenario_id: str
    question: str
    runs: tuple[ResearchBenchmarkRun, ...]
    repeat_speedup_ratio: float | None
    warm_run_reuse_observed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "question": self.question,
            "run_count": len(self.runs),
            "repeat_speedup_ratio": self.repeat_speedup_ratio,
            "warm_run_reuse_observed": self.warm_run_reuse_observed,
            "runs": [run.to_dict() for run in self.runs],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def compute_evidence_store_revision(evidence_path: Path) -> str:
    """Return a content-addressed revision for a benchmark evidence JSONL file."""

    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def build_research_benchmark_run(
    result: BenchmarkResearchResult,
    *,
    scenario_id: str,
    run_number: int,
    run_temperature: str,
    wall_clock_duration_ms: int,
    evidence_store_revision: str | None = None,
) -> ResearchBenchmarkRun:
    """Project one completed research result into the stable benchmark schema."""

    if run_number < 1:
        raise ValueError("run_number must be at least 1.")
    if run_temperature not in {"cold", "warm"}:
        raise ValueError("run_temperature must be 'cold' or 'warm'.")
    if wall_clock_duration_ms < 0:
        raise ValueError("wall_clock_duration_ms must not be negative.")

    state = derive_research_state(result)
    bottleneck = build_session_bottleneck_report(result.trace)
    funnel = _build_conversion_funnel(result, state)
    first_grounded_ms = _known_time_to_first_grounded_information_ms(
        bottleneck,
        indexed_evidence_record_count=funnel.indexed_evidence_record_count,
        used_reretrieved_evidence=result.used_reretrieved_evidence,
    )

    return ResearchBenchmarkRun(
        schema_version=BENCHMARK_SCHEMA_VERSION,
        scenario_id=scenario_id,
        run_number=run_number,
        run_temperature=run_temperature,
        question=result.question,
        question_fingerprint=_question_fingerprint(result.question),
        session_id=result.session_id,
        evidence_store_revision=evidence_store_revision,
        wall_clock_duration_ms=wall_clock_duration_ms,
        known_time_to_first_grounded_information_ms=first_grounded_ms,
        final_state=state,
        narrative_releaseable=result.narrative_releaseable,
        used_reretrieved_evidence=result.used_reretrieved_evidence,
        funnel=funnel,
        bottleneck_report=bottleneck,
    )


def execute_research_benchmark(
    question: str,
    *,
    scenario_id: str,
    run_once: Callable[[str], BenchmarkResearchResult],
    repeats: int = 2,
    evidence_store_revision: Callable[[], str | None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ResearchBenchmarkSuite:
    """Run the same question repeatedly against one caller-owned mutable research store.

    The caller owns all infrastructure and side effects. Keeping the same ``run_once``
    closure and store across repetitions is what makes the second run a real reuse test.
    """

    if not question.strip():
        raise ValueError("question must be non-blank.")
    if not scenario_id.strip():
        raise ValueError("scenario_id must be non-blank.")
    if repeats < 1:
        raise ValueError("repeats must be at least 1.")

    runs: list[ResearchBenchmarkRun] = []
    for index in range(repeats):
        revision_before = evidence_store_revision() if evidence_store_revision is not None else None
        started = clock()
        result = run_once(question)
        elapsed_ms = max(0, int((clock() - started) * 1000))
        runs.append(
            build_research_benchmark_run(
                result,
                scenario_id=scenario_id,
                run_number=index + 1,
                run_temperature="cold" if index == 0 else "warm",
                wall_clock_duration_ms=elapsed_ms,
                evidence_store_revision=revision_before,
            )
        )

    repeat_speedup = _repeat_speedup_ratio(tuple(runs))
    warm_reuse = any(run.funnel.reuse_hit for run in runs[1:])
    return ResearchBenchmarkSuite(
        schema_version=BENCHMARK_SCHEMA_VERSION,
        scenario_id=scenario_id,
        question=question,
        runs=tuple(runs),
        repeat_speedup_ratio=repeat_speedup,
        warm_run_reuse_observed=warm_reuse,
    )


def _build_conversion_funnel(
    result: BenchmarkResearchResult,
    state: ResearchStateResult,
) -> ResearchConversionFunnel:
    discovery = result.discovery
    federated = discovery.federated_discovery if discovery is not None else None
    provider_statuses = federated.provider_statuses if federated is not None else ()
    provider_outcomes = Counter(status.outcome for status in provider_statuses)
    provider_attempt_count = sum(1 for status in provider_statuses if status.attempted)
    provider_degraded_count = sum(
        1 for status in provider_statuses if status.attempted and status.outcome != "success"
    )

    plan = discovery.acquisition_plan if discovery is not None else None
    plan_items = plan.items if plan is not None else ()
    dispositions = Counter(item.disposition for item in plan_items)

    parallel_retrieval = result.workflow.parallel_retrieval
    primary_cache_hit = (
        parallel_retrieval.primary.cache_hit if parallel_retrieval is not None else False
    )
    contradiction_cache_hit = (
        parallel_retrieval.contradiction.cache_hit if parallel_retrieval is not None else False
    )

    completion = result.grounded_completion
    routes = completion.acquisition_routes if completion is not None else ()
    attempted_routes = tuple(route for route in routes if route.attempted)
    persisted_paper_count = sum(route.persisted_count for route in attempted_routes)
    route_reused_count = sum(route.reused_count for route in attempted_routes)
    already_indexed_papers = (
        len(completion.already_indexed_paper_ids) if completion is not None else 0
    )
    reused_paper_count = route_reused_count + already_indexed_papers
    reretrieval_attempt_count = (
        1
        if completion is not None
        and (
            bool(completion.promoted_record_ids)
            or completion.reretrieval_report is not None
            or completion.reretrieval_error is not None
        )
        else 0
    )

    return ResearchConversionFunnel(
        indexed_evidence_record_count=state.indexed_evidence_record_count,
        provider_attempt_count=provider_attempt_count,
        provider_degraded_count=provider_degraded_count,
        provider_outcomes=tuple(sorted(provider_outcomes.items())),
        discovery_candidate_count=len(federated.candidates) if federated is not None else 0,
        acquisition_plan_item_count=len(plan_items),
        acquisition_dispositions=tuple(sorted(dispositions.items())),
        already_indexed_candidate_count=dispositions.get("already_indexed", 0),
        eligible_full_text_candidate_count=dispositions.get("eligible_full_text", 0),
        acquisition_route_attempt_count=len(attempted_routes),
        acquisition_candidate_attempt_count=sum(
            len(route.candidate_ids) for route in attempted_routes
        ),
        persisted_paper_count=persisted_paper_count,
        reused_paper_count=reused_paper_count,
        available_paper_count=len(completion.paper_ids) if completion is not None else 0,
        draft_item_count=completion.draft_item_count if completion is not None else 0,
        classified_item_count=completion.classified_item_count if completion is not None else 0,
        staged_record_count=len(completion.staged_record_ids) if completion is not None else 0,
        grounded_record_count=len(completion.grounded_record_ids) if completion is not None else 0,
        promoted_evidence_record_count=(
            len(completion.promoted_record_ids) if completion is not None else 0
        ),
        grounding_failure_count=len(completion.grounding_failures) if completion is not None else 0,
        reretrieval_attempt_count=reretrieval_attempt_count,
        primary_indexed_retrieval_cache_hit=primary_cache_hit,
        contradiction_indexed_retrieval_cache_hit=contradiction_cache_hit,
        reuse_hit=(
            reused_paper_count > 0
            or dispositions.get("already_indexed", 0) > 0
            or primary_cache_hit
            or contradiction_cache_hit
        ),
    )


def _known_time_to_first_grounded_information_ms(
    report: SessionBottleneckReport,
    *,
    indexed_evidence_record_count: int,
    used_reretrieved_evidence: bool,
) -> int | None:
    if indexed_evidence_record_count > 0:
        target = ResearchPipelineStage.INDEXED_RETRIEVAL
    elif used_reretrieved_evidence:
        target = ResearchPipelineStage.RERETRIEVAL
    else:
        return None

    timing_by_stage = {stage.stage: stage for stage in report.stages}
    total = 0
    for stage in ResearchPipelineStage:
        timing = timing_by_stage.get(stage)
        if timing is not None:
            if timing.known_duration_ms is None:
                return None
            total += timing.known_duration_ms
        if stage is target:
            return total
    return None


def _repeat_speedup_ratio(runs: tuple[ResearchBenchmarkRun, ...]) -> float | None:
    if len(runs) < 2:
        return None
    first = runs[0].wall_clock_duration_ms
    second = runs[1].wall_clock_duration_ms
    if second <= 0:
        return None
    return round(first / second, 3)


def _question_fingerprint(question: str) -> str:
    normalized = " ".join(question.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "BenchmarkResearchResult",
    "ResearchBenchmarkRun",
    "ResearchBenchmarkSuite",
    "ResearchConversionFunnel",
    "build_research_benchmark_run",
    "compute_evidence_store_revision",
    "execute_research_benchmark",
]
