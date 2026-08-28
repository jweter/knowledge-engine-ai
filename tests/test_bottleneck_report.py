from __future__ import annotations

import json

from knowledge_engine_ai.orchestrator.bottleneck_report import (
    ResearchPipelineStage,
    build_session_bottleneck_report,
    classify_workflow_node,
)
from knowledge_engine_ai.orchestrator.observability import EventTrace, SessionTrace


def _event(
    event_id: str,
    workflow_node: str,
    *,
    duration_ms: int | None,
    succeeded: bool = True,
) -> EventTrace:
    return EventTrace(
        event_id=event_id,
        workflow_node=workflow_node,
        executor_type="deterministic_tool",
        tool_name="tool",
        model_name=None,
        succeeded=succeeded,
        duration_ms=duration_ms,
        notes=None,
        source_ids=(),
    )


def _trace(*events: EventTrace) -> SessionTrace:
    known = [event.duration_ms for event in events if event.duration_ms is not None]
    return SessionTrace(
        session_id="session-1",
        question="Does Monster Energy affect blood pressure?",
        events=events,
        failed_events=tuple(event for event in events if not event.succeeded),
        total_duration_ms=sum(known) if known else None,
        evidence_record_ids=(),
    )


def test_parallel_retrieval_duration_is_not_double_counted() -> None:
    trace = _trace(
        _event("primary", "retrieval_and_evidence_intelligence", duration_ms=900),
        _event("contradiction", "contradiction_oriented_retrieval", duration_ms=900),
        _event("synthesis", "synthesis", duration_ms=200),
    )

    report = build_session_bottleneck_report(trace)

    assert report.raw_event_duration_sum_ms == 2000
    assert report.adjusted_known_duration_ms == 1100
    assert report.parallel_overlap_adjustment_ms == 900
    assert report.slowest_stage is ResearchPipelineStage.INDEXED_RETRIEVAL
    assert report.slowest_event is not None
    assert report.slowest_event.event_id == "primary"
    assert report.slowest_event.duration_ms == 900

    retrieval = next(
        stage for stage in report.stages if stage.stage is ResearchPipelineStage.INDEXED_RETRIEVAL
    )
    assert retrieval.known_duration_ms == 900
    assert retrieval.event_count == 2
    assert retrieval.timing_complete is True


def test_failures_and_untimed_events_remain_visible() -> None:
    trace = _trace(
        _event("discover", "federated_discovery", duration_ms=1200, succeeded=False),
        _event("acquire", "acquisition_plan", duration_ms=None),
    )

    report = build_session_bottleneck_report(trace)

    assert report.event_count == 2
    assert report.timed_event_count == 1
    assert report.timing_complete is False
    assert report.failed_event_ids == ("discover",)
    assert report.untimed_event_ids == ("acquire",)
    assert report.slowest_stage is ResearchPipelineStage.DISCOVERY

    acquisition = next(
        stage for stage in report.stages if stage.stage is ResearchPipelineStage.ACQUISITION
    )
    assert acquisition.known_duration_ms is None
    assert acquisition.timed_event_count == 0
    assert acquisition.untimed_event_count == 1


def test_future_pipeline_nodes_map_to_stable_stage_taxonomy() -> None:
    expected = {
        "query_decomposition": ResearchPipelineStage.QUESTION_INTERPRETATION,
        "retrieval_adequacy": ResearchPipelineStage.ADEQUACY,
        "provider_search_batch": ResearchPipelineStage.DISCOVERY,
        "full_text_acquire": ResearchPipelineStage.ACQUISITION,
        "grounded_extraction_promotion": ResearchPipelineStage.EXTRACTION_PROMOTION,
        "re_retrieval_after_promotion": ResearchPipelineStage.RERETRIEVAL,
        "claim_verification": ResearchPipelineStage.SYNTHESIS_VERIFICATION,
        "session_report_build": ResearchPipelineStage.REPORT_CLOSE,
    }

    assert {node: classify_workflow_node(node) for node in expected} == expected


def test_unknown_node_is_preserved_as_other_instead_of_guessed() -> None:
    trace = _trace(_event("future", "new_unclassified_capability", duration_ms=75))

    report = build_session_bottleneck_report(trace)

    assert report.stages[0].stage is ResearchPipelineStage.OTHER
    assert report.stages[0].workflow_nodes == ("new_unclassified_capability",)
    assert report.adjusted_known_duration_ms == 75


def test_stage_output_order_is_stable_product_order_not_event_order() -> None:
    trace = _trace(
        _event("synthesis", "synthesis", duration_ms=100),
        _event("retrieval", "retrieval_and_evidence_intelligence", duration_ms=300),
        _event("discovery", "federated_discovery", duration_ms=200),
    )

    report = build_session_bottleneck_report(trace)

    assert [stage.stage for stage in report.stages] == [
        ResearchPipelineStage.INDEXED_RETRIEVAL,
        ResearchPipelineStage.DISCOVERY,
        ResearchPipelineStage.SYNTHESIS_VERIFICATION,
    ]


def test_json_contract_is_inspectable_and_version_independent_of_narrative() -> None:
    trace = _trace(
        _event("retrieval", "retrieval_and_evidence_intelligence", duration_ms=500),
        _event("discovery", "federated_discovery", duration_ms=800),
    )

    payload = json.loads(build_session_bottleneck_report(trace).to_json())

    assert payload["session_id"] == "session-1"
    assert payload["slowest_stage"] == "discovery"
    assert payload["slowest_event"]["event_id"] == "discovery"
    assert payload["adjusted_known_duration_ms"] == 1300
    assert payload["failed_event_ids"] == []
    assert payload["stages"][0]["stage"] == "indexed_retrieval"
