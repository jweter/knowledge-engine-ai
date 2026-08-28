from __future__ import annotations

from knowledge_engine_ai.copilot.grounded_completion import GroundedCompletionResult
from knowledge_engine_ai.copilot.run_research_question import _record_grounded_completion_events
from knowledge_engine_ai.sessions.models import ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection


def test_grounded_completion_durations_are_persisted_on_session_events() -> None:
    repository = SessionRepository(new_connection(":memory:"))
    repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id="session-timing",
            created_at="2026-08-28T00:00:00Z",
            updated_at="2026-08-28T00:00:00Z",
            user_question_original="Does music improve endurance?",
            status=SessionStatus.RUNNING,
        )
    )
    result = GroundedCompletionResult(
        attempted=True,
        search_run_id="search-1",
        research_question_id="rq-1",
        acquisition_duration_ms=1200,
        extraction_duration_ms=3400,
        reretrieval_duration_ms=5600,
    )

    _record_grounded_completion_events(repository, session_id="session-timing", result=result)

    events = repository.list_events("session-timing")
    assert [event.workflow_node for event in events] == [
        "grounded_acquisition",
        "grounded_extraction",
        "grounded_reretrieval",
    ]
    assert [event.duration_ms for event in events] == [1200, 3400, 5600]


def test_grounded_completion_to_dict_exposes_phase_timings() -> None:
    result = GroundedCompletionResult(
        attempted=True,
        search_run_id="search-1",
        research_question_id="rq-1",
        acquisition_duration_ms=12,
        extraction_duration_ms=34,
        reretrieval_duration_ms=56,
    )

    payload = result.to_dict()

    assert payload["acquisition_duration_ms"] == 12
    assert payload["extraction_duration_ms"] == 34
    assert payload["reretrieval_duration_ms"] == 56
