"""BT-2: research conversion-funnel report (issue #88).

Pure read-side projection over facts `run_research_question` already
computed -- the same posture `bottleneck_report.py` and `progress_report.py`
already established. It answers, for one completed research session, how
many candidates/papers/records moved through each stage of the arbitrary-
question research funnel and where the largest drop-off happened. It does
not judge evidence quality, adequacy, or scientific correctness, and it
never re-derives a count `DiscoveryAugmentationResult`, `GroundedCompletion
Result`, or `ResearchProgressReport` already computed -- only arithmetic
already implied by those durable facts (e.g. "rejected after
classification" = classified count minus promoted count).

## Funnel stages

```text
federated discovery candidates / citation-snowball candidates (leads only)
  -> acquisition-plan disposition (already indexed / full-text eligible /
     metadata only / skipped for budget / not resolved)
  -> acquisition route outcomes (attempted / skipped / failed, persisted vs
     reused papers)
  -> extraction (draft -> classified -> staged -> grounding-verified ->
     durably promoted, with a rejected-after-classification remainder)
  -> re-retrieval (attempted, succeeded, evidence-record count)
```

`indexed_evidence_record_count` and the bottleneck timings this module
sums are reused from `progress_report.py`'s own already-derived fields
rather than re-computed here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import GroundedCompletionResult
from knowledge_engine_ai.copilot.progress_report import ResearchProgressReport
from knowledge_engine_ai.orchestrator.bottleneck_report import (
    ResearchPipelineStage,
    SessionBottleneckReport,
)

RESEARCH_CONVERSION_FUNNEL_SCHEMA_VERSION = 1

# Canonical pipeline order for cumulative "time to X" sums -- matches
# `ResearchPipelineStage`'s own declaration order, which is itself the
# pipeline's real execution order (see `bottleneck_report.py`).
_PIPELINE_ORDER: tuple[ResearchPipelineStage, ...] = tuple(ResearchPipelineStage)


@dataclass(frozen=True)
class AcquisitionPlanFunnel:
    """Core's resolved candidate-disposition counts for one acquisition plan."""

    resolved_candidate_count: int
    already_indexed_count: int
    full_text_eligible_count: int
    metadata_only_count: int
    skipped_budget_count: int
    missing_candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "resolved_candidate_count": self.resolved_candidate_count,
            "already_indexed_count": self.already_indexed_count,
            "full_text_eligible_count": self.full_text_eligible_count,
            "metadata_only_count": self.metadata_only_count,
            "skipped_budget_count": self.skipped_budget_count,
            "missing_candidate_count": self.missing_candidate_count,
        }


@dataclass(frozen=True)
class AcquisitionFunnel:
    """Route-level acquisition outcome counts for one grounded-completion pass."""

    routes_attempted: int
    routes_skipped: int
    routes_failed: int
    papers_persisted: int
    papers_reused: int

    def to_dict(self) -> dict[str, object]:
        return {
            "routes_attempted": self.routes_attempted,
            "routes_skipped": self.routes_skipped,
            "routes_failed": self.routes_failed,
            "papers_persisted": self.papers_persisted,
            "papers_reused": self.papers_reused,
        }


@dataclass(frozen=True)
class ExtractionFunnel:
    """Extraction/grounding/promotion conversion counts for one grounded-completion pass."""

    draft_item_count: int
    classified_item_count: int
    staged_record_count: int
    grounded_record_count: int
    promoted_record_count: int
    grounding_failure_count: int
    rejected_after_classification_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "draft_item_count": self.draft_item_count,
            "classified_item_count": self.classified_item_count,
            "staged_record_count": self.staged_record_count,
            "grounded_record_count": self.grounded_record_count,
            "promoted_record_count": self.promoted_record_count,
            "grounding_failure_count": self.grounding_failure_count,
            "rejected_after_classification_count": self.rejected_after_classification_count,
        }


@dataclass(frozen=True)
class ResearchConversionFunnelReport:
    """BT-2 (issue #88): durable question-to-report conversion funnel for one session."""

    schema_version: int
    session_id: str
    discovery_triggered: bool
    federated_discovery_candidate_count: int
    citation_snowball_candidate_count: int
    acquisition_plan: AcquisitionPlanFunnel | None
    acquisition: AcquisitionFunnel | None
    extraction: ExtractionFunnel | None
    reretrieval_attempted: bool
    reretrieval_succeeded: bool
    reretrieval_evidence_record_count: int
    indexed_evidence_record_count: int
    newly_promoted_evidence_record_count: int
    time_to_first_grounded_information_ms: int | None
    time_to_final_report_ms: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "discovery_triggered": self.discovery_triggered,
            "federated_discovery_candidate_count": self.federated_discovery_candidate_count,
            "citation_snowball_candidate_count": self.citation_snowball_candidate_count,
            "acquisition_plan": (
                self.acquisition_plan.to_dict() if self.acquisition_plan is not None else None
            ),
            "acquisition": (self.acquisition.to_dict() if self.acquisition is not None else None),
            "extraction": (self.extraction.to_dict() if self.extraction is not None else None),
            "reretrieval_attempted": self.reretrieval_attempted,
            "reretrieval_succeeded": self.reretrieval_succeeded,
            "reretrieval_evidence_record_count": self.reretrieval_evidence_record_count,
            "indexed_evidence_record_count": self.indexed_evidence_record_count,
            "newly_promoted_evidence_record_count": self.newly_promoted_evidence_record_count,
            "time_to_first_grounded_information_ms": self.time_to_first_grounded_information_ms,
            "time_to_final_report_ms": self.time_to_final_report_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class ResearchFunnelResultLike(Protocol):
    """The subset of `ResearchQuestionResult` this projection needs.

    `progress_report` must already be populated -- `run_research_question`
    always builds BT-6's progress report before this BT-2 projection runs.
    """

    @property
    def session_id(self) -> str: ...

    @property
    def discovery(self) -> DiscoveryAugmentationResult | None: ...

    @property
    def grounded_completion(self) -> GroundedCompletionResult | None: ...

    @property
    def progress_report(self) -> ResearchProgressReport | None: ...


def build_research_conversion_funnel_report(
    result: ResearchFunnelResultLike,
) -> ResearchConversionFunnelReport:
    """Project one completed `run_research_question` result into a BT-2 funnel report.

    Every count/duration here is read directly from `DiscoveryAugmentation
    Result`, `GroundedCompletionResult`, or `progress_report`'s already-
    derived indexed-evidence IDs and per-stage bottleneck timings -- nothing
    is estimated or fabricated.
    """

    progress = result.progress_report
    if progress is None:
        raise ValueError(
            "ResearchConversionFunnelReport requires an already-built progress_report; "
            "call build_research_progress_report first."
        )

    discovery = result.discovery
    completion = result.grounded_completion

    discovery_triggered = discovery.triggered if discovery is not None else False
    federated_count = (
        len(discovery.federated_discovery.candidates)
        if discovery is not None and discovery.federated_discovery is not None
        else 0
    )
    snowball_count = (
        len(discovery.citation_snowball.candidates)
        if discovery is not None and discovery.citation_snowball is not None
        else 0
    )

    acquisition_plan = _acquisition_plan_funnel(discovery)
    acquisition = _acquisition_funnel(completion)
    extraction = _extraction_funnel(completion)

    reretrieval_attempted = completion is not None and bool(completion.promoted_record_ids)
    reretrieval_succeeded = completion is not None and completion.reretrieval_report is not None
    reretrieval_evidence_record_count = _reretrieval_evidence_record_count(completion)

    indexed_count = len(progress.indexed_evidence_record_ids)
    newly_promoted_count = len(completion.promoted_record_ids) if completion is not None else 0

    bottleneck = progress.bottleneck_report
    time_to_first = _time_to_first_grounded_information_ms(
        bottleneck,
        indexed_available=indexed_count > 0,
        # Gate on the re-retrieval report actually carrying evidence records,
        # not command success alone -- a successful re-retrieval call that
        # happens to return an empty report produced no grounded information.
        reretrieval_succeeded=reretrieval_succeeded and reretrieval_evidence_record_count > 0,
    )

    return ResearchConversionFunnelReport(
        schema_version=RESEARCH_CONVERSION_FUNNEL_SCHEMA_VERSION,
        session_id=result.session_id,
        discovery_triggered=discovery_triggered,
        federated_discovery_candidate_count=federated_count,
        citation_snowball_candidate_count=snowball_count,
        acquisition_plan=acquisition_plan,
        acquisition=acquisition,
        extraction=extraction,
        reretrieval_attempted=reretrieval_attempted,
        reretrieval_succeeded=reretrieval_succeeded,
        reretrieval_evidence_record_count=reretrieval_evidence_record_count,
        indexed_evidence_record_count=indexed_count,
        newly_promoted_evidence_record_count=newly_promoted_count,
        time_to_first_grounded_information_ms=time_to_first,
        time_to_final_report_ms=bottleneck.adjusted_known_duration_ms,
    )


def _acquisition_plan_funnel(
    discovery: DiscoveryAugmentationResult | None,
) -> AcquisitionPlanFunnel | None:
    if discovery is None or discovery.acquisition_plan is None:
        return None
    plan = discovery.acquisition_plan
    return AcquisitionPlanFunnel(
        resolved_candidate_count=plan.resolved_candidate_count,
        already_indexed_count=plan.already_indexed_count,
        full_text_eligible_count=plan.full_text_selected_count,
        metadata_only_count=plan.metadata_only_count,
        skipped_budget_count=plan.skipped_budget_count,
        missing_candidate_count=plan.missing_candidate_count,
    )


def _acquisition_funnel(completion: GroundedCompletionResult | None) -> AcquisitionFunnel | None:
    if completion is None or not completion.attempted:
        return None
    routes = completion.acquisition_routes
    return AcquisitionFunnel(
        routes_attempted=sum(1 for route in routes if route.attempted),
        routes_skipped=sum(1 for route in routes if not route.attempted),
        routes_failed=sum(1 for route in routes if route.error is not None),
        papers_persisted=sum(route.persisted_count for route in routes),
        papers_reused=sum(route.reused_count for route in routes),
    )


def _extraction_funnel(completion: GroundedCompletionResult | None) -> ExtractionFunnel | None:
    if completion is None or not completion.attempted or not completion.paper_ids:
        return None
    rejected = max(0, completion.classified_item_count - len(completion.promoted_record_ids))
    return ExtractionFunnel(
        draft_item_count=completion.draft_item_count,
        classified_item_count=completion.classified_item_count,
        staged_record_count=len(completion.staged_record_ids),
        grounded_record_count=len(completion.grounded_record_ids),
        promoted_record_count=len(completion.promoted_record_ids),
        grounding_failure_count=len(completion.grounding_failures),
        rejected_after_classification_count=rejected,
    )


def _reretrieval_evidence_record_count(completion: GroundedCompletionResult | None) -> int:
    if completion is None or completion.reretrieval_report is None:
        return 0
    return sum(len(paper.evidence_records) for paper in completion.reretrieval_report.papers)


def _time_to_first_grounded_information_ms(
    bottleneck: SessionBottleneckReport,
    *,
    indexed_available: bool,
    reretrieval_succeeded: bool,
) -> int | None:
    """Cumulative known stage duration through the first point grounded evidence existed.

    Indexed evidence, when present, is available as soon as local retrieval
    finishes, so the cutoff is `INDEXED_RETRIEVAL`. Otherwise, if grounded
    completion durably promoted and re-retrieved new evidence, the cutoff is
    `RERETRIEVAL`. If neither ever produced grounded evidence, there is no
    "first grounded information" instant to report.
    """

    if indexed_available:
        cutoff = ResearchPipelineStage.INDEXED_RETRIEVAL
    elif reretrieval_succeeded:
        cutoff = ResearchPipelineStage.RERETRIEVAL
    else:
        return None
    return _cumulative_known_duration_through(bottleneck, cutoff)


def _cumulative_known_duration_through(
    bottleneck: SessionBottleneckReport, cutoff: ResearchPipelineStage
) -> int | None:
    timings_by_stage = {timing.stage: timing for timing in bottleneck.stages}
    cutoff_index = _PIPELINE_ORDER.index(cutoff)
    total = 0
    known_any = False
    for stage in _PIPELINE_ORDER[: cutoff_index + 1]:
        timing = timings_by_stage.get(stage)
        if timing is None or timing.known_duration_ms is None:
            continue
        total += timing.known_duration_ms
        known_any = True
    return total if known_any else None


__all__ = [
    "RESEARCH_CONVERSION_FUNNEL_SCHEMA_VERSION",
    "AcquisitionFunnel",
    "AcquisitionPlanFunnel",
    "ExtractionFunnel",
    "ResearchConversionFunnelReport",
    "ResearchFunnelResultLike",
    "build_research_conversion_funnel_report",
]
