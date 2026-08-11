from __future__ import annotations

from knowledge_engine_ai.orchestrator.observability import build_session_trace, render_session_trace
from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession, SessionStatus


def _session(**overrides: object) -> ResearchSession:
    base: dict[str, object] = {
        "schema_version": 1,
        "session_id": "sess-1",
        "created_at": "2026-08-11T00:00:00Z",
        "updated_at": "2026-08-11T00:00:00Z",
        "user_question_original": "does semaglutide reduce body weight",
        "status": SessionStatus.RUNNING,
    }
    base.update(overrides)
    return ResearchSession(**base)  # type: ignore[arg-type]


def _event(**overrides: object) -> ResearchEvent:
    base: dict[str, object] = {
        "event_id": "ev-1",
        "session_id": "sess-1",
        "timestamp": "2026-08-11T00:00:01Z",
        "workflow_node": "retrieval_and_evidence_intelligence",
        "executor_type": "deterministic_tool",
        "validation_status": "succeeded",
        "tool_name": "ke evidence-report",
        "duration_ms": 120,
        "source_ids": ("ev-a", "ev-b"),
    }
    base.update(overrides)
    return ResearchEvent(**base)  # type: ignore[arg-type]


def test_all_succeeded_true_when_every_event_succeeded() -> None:
    trace = build_session_trace(_session(), (_event(),))

    assert trace.all_succeeded is True
    assert trace.failed_events == ()


def test_failed_event_surfaces_in_failed_events_with_its_notes() -> None:
    failed = _event(
        event_id="ev-2",
        workflow_node="statistical_verification",
        validation_status="failed",
        notes="ke exited non-zero",
        duration_ms=50,
        source_ids=(),
    )
    trace = build_session_trace(_session(), (_event(), failed))

    assert trace.all_succeeded is False
    assert len(trace.failed_events) == 1
    assert trace.failed_events[0].workflow_node == "statistical_verification"
    assert trace.failed_events[0].notes == "ke exited non-zero"


def test_total_duration_sums_only_known_durations() -> None:
    timed = _event(duration_ms=100)
    untimed = _event(event_id="ev-2", workflow_node="evidence_map", duration_ms=None)
    trace = build_session_trace(_session(), (timed, untimed))

    assert trace.total_duration_ms == 100


def test_total_duration_is_none_when_no_event_has_a_known_duration() -> None:
    untimed = _event(duration_ms=None)
    trace = build_session_trace(_session(), (untimed,))

    assert trace.total_duration_ms is None


def test_evidence_record_ids_deduplicated_in_order_of_first_appearance() -> None:
    first = _event(source_ids=("ev-b", "ev-a"))
    second = _event(
        event_id="ev-2",
        workflow_node="contradiction_oriented_retrieval",
        source_ids=("ev-a", "ev-c"),
    )
    trace = build_session_trace(_session(), (first, second))

    assert trace.evidence_record_ids == ("ev-b", "ev-a", "ev-c")


def test_render_session_trace_answers_all_six_questions() -> None:
    failed = _event(
        event_id="ev-2",
        workflow_node="statistical_verification",
        validation_status="failed",
        notes="ke exited non-zero",
        model_name=None,
        tool_name="ke statistical-verify",
        duration_ms=75,
        source_ids=(),
    )
    trace = build_session_trace(_session(), (_event(), failed))

    rendered = render_session_trace(trace)

    assert "does semaglutide reduce body weight" in rendered  # why
    assert "retrieval_and_evidence_intelligence" in rendered  # what ran
    assert "ke evidence-report" in rendered  # what tool was used
    assert "120ms" in rendered  # where time was spent
    assert "ke exited non-zero" in rendered  # what failed
    assert "ev-a" in rendered and "ev-b" in rendered  # what evidence supported the output
