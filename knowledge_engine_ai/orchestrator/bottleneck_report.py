"""Deterministic question-to-report bottleneck analysis over durable session traces.

The Knowledge Engine already records per-step ``duration_ms`` values on
``ResearchEvent`` and projects them into :class:`SessionTrace`.  This module turns
that event-level trace into a stable research-pipeline view so benchmarks and Web
can answer a more useful engineering question: *where did this research run spend
its time, and what failed or was not timed?*

This is observability only.  It does not change research execution, evidence
adequacy, confidence, or scientific conclusions.

One accounting detail matters today: primary and contradiction-oriented retrieval
run concurrently and both ResearchEvents intentionally carry the same combined
wall-clock duration.  Summing those two event durations would double-count elapsed
time.  The ``indexed_retrieval`` stage therefore treats those two known nodes as
one parallel group and uses the group's maximum duration.  Other events remain
serial unless a future executor explicitly adds another parallel-group rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from knowledge_engine_ai.orchestrator.observability import EventTrace, SessionTrace


class ResearchPipelineStage(StrEnum):
    """Stable product-stage taxonomy from question interpretation through report close."""

    QUESTION_INTERPRETATION = "question_interpretation"
    INDEXED_RETRIEVAL = "indexed_retrieval"
    ADEQUACY = "adequacy"
    DISCOVERY = "discovery"
    ACQUISITION = "acquisition"
    EXTRACTION_PROMOTION = "extraction_promotion"
    RERETRIEVAL = "reretrieval"
    SYNTHESIS_VERIFICATION = "synthesis_verification"
    REPORT_CLOSE = "report_close"
    OTHER = "other"


@dataclass(frozen=True)
class StageBottleneckTiming:
    """Observed event/timing facts for one research stage."""

    stage: ResearchPipelineStage
    known_duration_ms: int | None
    timed_event_count: int
    untimed_event_count: int
    failed_event_count: int
    event_ids: tuple[str, ...]
    workflow_nodes: tuple[str, ...]

    @property
    def event_count(self) -> int:
        return self.timed_event_count + self.untimed_event_count

    @property
    def timing_complete(self) -> bool:
        return self.event_count > 0 and self.untimed_event_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "known_duration_ms": self.known_duration_ms,
            "event_count": self.event_count,
            "timed_event_count": self.timed_event_count,
            "untimed_event_count": self.untimed_event_count,
            "failed_event_count": self.failed_event_count,
            "timing_complete": self.timing_complete,
            "event_ids": list(self.event_ids),
            "workflow_nodes": list(self.workflow_nodes),
        }


@dataclass(frozen=True)
class SlowestEvent:
    """The longest individually timed ResearchEvent in one trace."""

    event_id: str
    workflow_node: str
    stage: ResearchPipelineStage
    duration_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "workflow_node": self.workflow_node,
            "stage": self.stage.value,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class SessionBottleneckReport:
    """Deterministic bottleneck projection for one completed or partial session trace."""

    session_id: str
    question: str
    stages: tuple[StageBottleneckTiming, ...]
    event_count: int
    timed_event_count: int
    raw_event_duration_sum_ms: int | None
    adjusted_known_duration_ms: int | None
    parallel_overlap_adjustment_ms: int
    slowest_stage: ResearchPipelineStage | None
    slowest_event: SlowestEvent | None
    failed_event_ids: tuple[str, ...]
    untimed_event_ids: tuple[str, ...]

    @property
    def timing_complete(self) -> bool:
        return self.event_count > 0 and self.timed_event_count == self.event_count

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "question": self.question,
            "event_count": self.event_count,
            "timed_event_count": self.timed_event_count,
            "timing_complete": self.timing_complete,
            "raw_event_duration_sum_ms": self.raw_event_duration_sum_ms,
            "adjusted_known_duration_ms": self.adjusted_known_duration_ms,
            "parallel_overlap_adjustment_ms": self.parallel_overlap_adjustment_ms,
            "slowest_stage": self.slowest_stage.value if self.slowest_stage is not None else None,
            "slowest_event": self.slowest_event.to_dict()
            if self.slowest_event is not None
            else None,
            "failed_event_ids": list(self.failed_event_ids),
            "untimed_event_ids": list(self.untimed_event_ids),
            "stages": [stage.to_dict() for stage in self.stages],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


# These two events are one concurrent retrieval call.  ``workflow.py`` records the
# combined wall-clock duration on both events so each branch is independently
# inspectable; bottleneck aggregation must count that elapsed interval once.
_PARALLEL_RETRIEVAL_NODES = frozenset(
    {
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
    }
)

_EXACT_STAGE_BY_NODE: dict[str, ResearchPipelineStage] = {
    "retrieval_and_evidence_intelligence": ResearchPipelineStage.INDEXED_RETRIEVAL,
    "contradiction_oriented_retrieval": ResearchPipelineStage.INDEXED_RETRIEVAL,
    "federated_discovery": ResearchPipelineStage.DISCOVERY,
    "citation_snowball": ResearchPipelineStage.DISCOVERY,
    "acquisition_plan": ResearchPipelineStage.ACQUISITION,
    "synthesis": ResearchPipelineStage.SYNTHESIS_VERIFICATION,
    "evidence_map": ResearchPipelineStage.SYNTHESIS_VERIFICATION,
    "statistical_verification": ResearchPipelineStage.SYNTHESIS_VERIFICATION,
}


def classify_workflow_node(workflow_node: str) -> ResearchPipelineStage:
    """Map a durable workflow-node name into the stable product-stage taxonomy.

    Existing nodes are exact-mapped first.  The conservative token rules below
    keep future GQR nodes useful in bottleneck reports before every new node has
    an explicit mapping.  Unknown names remain visible as ``other`` rather than
    being guessed into a scientifically meaningful stage.
    """

    exact = _EXACT_STAGE_BY_NODE.get(workflow_node)
    if exact is not None:
        return exact

    normalized = workflow_node.strip().lower().replace("-", "_")

    if any(token in normalized for token in ("query_decom", "query_plan", "interpret", "normaliz")):
        return ResearchPipelineStage.QUESTION_INTERPRETATION
    if any(token in normalized for token in ("re_retrieval", "reretrieval", "retrieve_again")):
        return ResearchPipelineStage.RERETRIEVAL
    if any(token in normalized for token in ("adequacy", "coverage_gap", "sufficiency")):
        return ResearchPipelineStage.ADEQUACY
    if any(
        token in normalized for token in ("federated", "discovery", "snowball", "provider_search")
    ):
        return ResearchPipelineStage.DISCOVERY
    if any(token in normalized for token in ("acquisition", "acquire", "full_text")):
        return ResearchPipelineStage.ACQUISITION
    if any(
        token in normalized
        for token in ("extract", "grounding", "promotion", "promote", "parse_paper")
    ):
        return ResearchPipelineStage.EXTRACTION_PROMOTION
    if any(
        token in normalized
        for token in ("synthesis", "verification", "verify", "evidence_map", "statistical")
    ):
        return ResearchPipelineStage.SYNTHESIS_VERIFICATION
    if any(
        token in normalized
        for token in ("session_report", "report", "close_gate", "session_close", "isa_close")
    ):
        return ResearchPipelineStage.REPORT_CLOSE
    if "retrieval" in normalized or "retrieve" in normalized:
        return ResearchPipelineStage.INDEXED_RETRIEVAL
    return ResearchPipelineStage.OTHER


def build_session_bottleneck_report(trace: SessionTrace) -> SessionBottleneckReport:
    """Aggregate one :class:`SessionTrace` without reinterpreting research results."""

    events_by_stage: dict[ResearchPipelineStage, list[EventTrace]] = {}
    for event in trace.events:
        stage = classify_workflow_node(event.workflow_node)
        events_by_stage.setdefault(stage, []).append(event)

    stage_timings: list[StageBottleneckTiming] = []
    for stage in ResearchPipelineStage:
        stage_events = events_by_stage.get(stage)
        if not stage_events:
            continue
        stage_timings.append(_build_stage_timing(stage, tuple(stage_events)))

    known_stage_timings = [stage for stage in stage_timings if stage.known_duration_ms is not None]
    adjusted_known_duration_ms = (
        sum(
            stage.known_duration_ms
            for stage in known_stage_timings
            if stage.known_duration_ms is not None
        )
        if known_stage_timings
        else None
    )

    raw_duration = trace.total_duration_ms
    overlap_adjustment = (
        raw_duration - adjusted_known_duration_ms
        if raw_duration is not None and adjusted_known_duration_ms is not None
        else 0
    )
    # A future trace can contain timing semantics we do not yet know how to
    # de-overlap. Never report a negative "adjustment" if that happens.
    overlap_adjustment = max(0, overlap_adjustment)

    slowest_stage = None
    if known_stage_timings:
        slowest_stage = max(
            known_stage_timings,
            key=lambda item: item.known_duration_ms if item.known_duration_ms is not None else -1,
        ).stage

    timed_events = tuple(event for event in trace.events if event.duration_ms is not None)
    slowest_event = None
    if timed_events:
        event = max(
            timed_events, key=lambda item: item.duration_ms if item.duration_ms is not None else -1
        )
        assert event.duration_ms is not None  # narrowed by timed_events
        slowest_event = SlowestEvent(
            event_id=event.event_id,
            workflow_node=event.workflow_node,
            stage=classify_workflow_node(event.workflow_node),
            duration_ms=event.duration_ms,
        )

    return SessionBottleneckReport(
        session_id=trace.session_id,
        question=trace.question,
        stages=tuple(stage_timings),
        event_count=len(trace.events),
        timed_event_count=len(timed_events),
        raw_event_duration_sum_ms=raw_duration,
        adjusted_known_duration_ms=adjusted_known_duration_ms,
        parallel_overlap_adjustment_ms=overlap_adjustment,
        slowest_stage=slowest_stage,
        slowest_event=slowest_event,
        failed_event_ids=tuple(event.event_id for event in trace.events if not event.succeeded),
        untimed_event_ids=tuple(
            event.event_id for event in trace.events if event.duration_ms is None
        ),
    )


def _build_stage_timing(
    stage: ResearchPipelineStage,
    events: tuple[EventTrace, ...],
) -> StageBottleneckTiming:
    timed = tuple(event for event in events if event.duration_ms is not None)
    known_duration_ms: int | None = None
    if timed:
        known_duration_ms = _stage_known_duration_ms(stage, timed)

    return StageBottleneckTiming(
        stage=stage,
        known_duration_ms=known_duration_ms,
        timed_event_count=len(timed),
        untimed_event_count=len(events) - len(timed),
        failed_event_count=sum(1 for event in events if not event.succeeded),
        event_ids=tuple(event.event_id for event in events),
        workflow_nodes=tuple(event.workflow_node for event in events),
    )


def _stage_known_duration_ms(
    stage: ResearchPipelineStage,
    timed_events: tuple[EventTrace, ...],
) -> int:
    if stage is not ResearchPipelineStage.INDEXED_RETRIEVAL:
        return sum(event.duration_ms for event in timed_events if event.duration_ms is not None)

    parallel_retrieval = tuple(
        event for event in timed_events if event.workflow_node in _PARALLEL_RETRIEVAL_NODES
    )
    serial_or_unknown_retrieval = tuple(
        event for event in timed_events if event.workflow_node not in _PARALLEL_RETRIEVAL_NODES
    )

    parallel_duration = max(
        (event.duration_ms for event in parallel_retrieval if event.duration_ms is not None),
        default=0,
    )
    serial_duration = sum(
        event.duration_ms for event in serial_or_unknown_retrieval if event.duration_ms is not None
    )
    return parallel_duration + serial_duration


__all__ = [
    "ResearchPipelineStage",
    "SessionBottleneckReport",
    "SlowestEvent",
    "StageBottleneckTiming",
    "build_session_bottleneck_report",
    "classify_workflow_node",
]
