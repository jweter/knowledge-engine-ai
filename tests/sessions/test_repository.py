from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import (
    DuplicateEventError,
    DuplicateSessionError,
    SessionRepository,
    UnknownSessionError,
    new_connection,
)


def _session(**overrides: object) -> ResearchSession:
    fields: dict[str, object] = {
        "schema_version": 1,
        "session_id": "session-1",
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "user_question_original": "Does semaglutide produce long-term weight loss?",
        "status": SessionStatus.PENDING,
    }
    fields.update(overrides)
    return ResearchSession(**fields)  # type: ignore[arg-type]


def _event(**overrides: object) -> ResearchEvent:
    fields: dict[str, object] = {
        "event_id": "event-1",
        "session_id": "session-1",
        "timestamp": "2026-08-09T00:00:01Z",
        "workflow_node": "corpus_retrieval",
        "executor_type": "deterministic",
    }
    fields.update(overrides)
    return ResearchEvent(**fields)  # type: ignore[arg-type]


@pytest.fixture
def repository() -> SessionRepository:
    connection = new_connection(":memory:")
    return SessionRepository(connection)


def test_create_and_get_session_round_trips(repository: SessionRepository) -> None:
    session = _session(domain_hints=("clinical_medicine",), research_plan_id="plan-1")
    repository.create_session(session)

    fetched = repository.get_session("session-1")

    assert fetched == session


def test_get_session_returns_none_for_unknown_id(repository: SessionRepository) -> None:
    assert repository.get_session("does-not-exist") is None


def test_create_session_twice_raises_duplicate_session_error(
    repository: SessionRepository,
) -> None:
    repository.create_session(_session())

    with pytest.raises(DuplicateSessionError):
        repository.create_session(_session())


def test_append_event_to_unknown_session_raises(repository: SessionRepository) -> None:
    with pytest.raises(UnknownSessionError):
        repository.append_event(_event())


def test_append_and_list_events_round_trips_in_order(repository: SessionRepository) -> None:
    repository.create_session(_session())
    first = _event(event_id="e1", workflow_node="corpus_retrieval")
    second = _event(
        event_id="e2",
        workflow_node="evidence_compare",
        parent_event_ids=("e1",),
        timestamp="2026-08-09T00:00:02Z",
    )

    repository.append_event(first)
    repository.append_event(second)

    events = repository.list_events("session-1")

    assert [event.event_id for event in events] == ["e1", "e2"]
    assert events[1].parent_event_ids == ("e1",)


def test_append_event_twice_raises_duplicate_event_error(repository: SessionRepository) -> None:
    repository.create_session(_session())
    repository.append_event(_event())

    with pytest.raises(DuplicateEventError):
        repository.append_event(_event())


def test_has_event_reflects_persisted_state(repository: SessionRepository) -> None:
    repository.create_session(_session())

    assert repository.has_event("event-1") is False

    repository.append_event(_event())

    assert repository.has_event("event-1") is True


def test_update_session_status_persists(repository: SessionRepository) -> None:
    repository.create_session(_session())

    repository.update_session_status(
        "session-1", SessionStatus.RUNNING, updated_at="2026-08-09T00:05:00Z"
    )

    fetched = repository.get_session("session-1")
    assert fetched is not None
    assert fetched.status == SessionStatus.RUNNING
    assert fetched.updated_at == "2026-08-09T00:05:00Z"


def test_update_session_status_for_unknown_session_raises(repository: SessionRepository) -> None:
    with pytest.raises(UnknownSessionError):
        repository.update_session_status(
            "does-not-exist", SessionStatus.RUNNING, updated_at="2026-08-09T00:00:00Z"
        )


def test_workflow_can_stop_and_resume_without_losing_or_duplicating_state(
    tmp_path: Path,
) -> None:
    """AI-O2's actual success criterion, exercised end to end against a real file-backed DB.

    Simulates a crash by dropping the first `SessionRepository`/connection
    entirely and opening a fresh one against the same database file --
    the resumed workflow does not know whether its last event committed,
    re-attempts it, and must get `DuplicateEventError` (already ran) or a
    clean append (did not run) with no duplicate row either way.
    """

    database_path = f"{tmp_path}/sessions.sqlite3"

    first_connection = new_connection(database_path)
    first_repository = SessionRepository(first_connection)
    first_repository.create_session(_session())
    first_repository.append_event(_event(event_id="e1"))
    first_connection.close()

    resumed_connection = new_connection(database_path)
    resumed_repository = SessionRepository(resumed_connection)

    if not resumed_repository.has_event("e1"):
        resumed_repository.append_event(_event(event_id="e1"))
    resumed_repository.append_event(_event(event_id="e2", timestamp="2026-08-09T00:00:02Z"))

    events = resumed_repository.list_events("session-1")
    assert [event.event_id for event in events] == ["e1", "e2"]

    with pytest.raises(DuplicateEventError):
        resumed_repository.append_event(_event(event_id="e1"))

    resumed_connection.close()
