from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import (
    DuplicateEventError,
    DuplicateSessionError,
    NarrativeAlreadyInvalidatedError,
    SessionNotSupersedableError,
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


def test_research_question_id_round_trips(repository: SessionRepository) -> None:
    session = _session(research_question_id="rq-abc123")
    repository.create_session(session)

    fetched = repository.get_session("session-1")

    assert fetched is not None
    assert fetched.research_question_id == "rq-abc123"


def test_research_question_id_defaults_to_none(repository: SessionRepository) -> None:
    repository.create_session(_session())

    fetched = repository.get_session("session-1")

    assert fetched is not None
    assert fetched.research_question_id is None


def test_answer_version_defaults_to_one(repository: SessionRepository) -> None:
    repository.create_session(_session())

    fetched = repository.get_session("session-1")

    assert fetched is not None
    assert fetched.answer_version == 1
    assert fetched.supersedes_session_id is None
    assert fetched.narrative_invalidated_at is None


def test_answer_version_and_supersedes_session_id_round_trip(
    repository: SessionRepository,
) -> None:
    repository.create_session(_session(session_id="session-1", status=SessionStatus.COMPLETED))
    repository.create_session(
        _session(
            session_id="session-2",
            answer_version=2,
            supersedes_session_id="session-1",
            research_question_id="rq-abc123",
        )
    )

    fetched = repository.get_session("session-2")

    assert fetched is not None
    assert fetched.answer_version == 2
    assert fetched.supersedes_session_id == "session-1"


def test_list_sessions_for_research_question_returns_thread_ordered_by_version(
    repository: SessionRepository,
) -> None:
    repository.create_session(
        _session(
            session_id="session-2",
            answer_version=2,
            supersedes_session_id="session-1",
            research_question_id="rq-abc123",
            created_at="2026-08-10T00:00:00Z",
        )
    )
    repository.create_session(
        _session(
            session_id="session-1",
            answer_version=1,
            research_question_id="rq-abc123",
            status=SessionStatus.SUPERSEDED,
            created_at="2026-08-09T00:00:00Z",
        )
    )
    repository.create_session(
        _session(session_id="session-other", research_question_id="rq-unrelated")
    )

    thread = repository.list_sessions_for_research_question("rq-abc123")

    assert [session.session_id for session in thread] == ["session-1", "session-2"]


def test_list_sessions_for_research_question_unknown_id_returns_empty(
    repository: SessionRepository,
) -> None:
    repository.create_session(_session(research_question_id="rq-abc123"))

    assert repository.list_sessions_for_research_question("rq-does-not-exist") == []


def test_record_narrative_invalidation_sets_field_and_appends_event(
    repository: SessionRepository,
) -> None:
    repository.create_session(_session(status=SessionStatus.COMPLETED))
    event = _event(
        event_id="invalidation-1",
        workflow_node="narrative_invalidated",
        executor_type="deterministic_policy",
        notes="canonical_id=work-1 doi=10.1/x flag=retracted",
    )

    repository.record_narrative_invalidation(event, invalidated_at="2026-08-22T12:00:00Z")

    fetched = repository.get_session("session-1")
    assert fetched is not None
    assert fetched.narrative_invalidated_at == "2026-08-22T12:00:00Z"
    # status is left untouched by design -- narrative_invalidated_at is a
    # parallel signal, not a status value.
    assert fetched.status == SessionStatus.COMPLETED
    events = repository.list_events("session-1")
    assert [event.event_id for event in events] == ["invalidation-1"]


def test_record_narrative_invalidation_twice_raises(repository: SessionRepository) -> None:
    repository.create_session(_session(status=SessionStatus.COMPLETED))
    repository.record_narrative_invalidation(
        _event(event_id="invalidation-1", workflow_node="narrative_invalidated"),
        invalidated_at="2026-08-22T12:00:00Z",
    )

    with pytest.raises(NarrativeAlreadyInvalidatedError):
        repository.record_narrative_invalidation(
            _event(event_id="invalidation-2", workflow_node="narrative_invalidated"),
            invalidated_at="2026-08-22T13:00:00Z",
        )


def test_record_narrative_invalidation_wrong_workflow_node_raises(
    repository: SessionRepository,
) -> None:
    repository.create_session(_session(status=SessionStatus.COMPLETED))

    with pytest.raises(ValueError, match="narrative_invalidated"):
        repository.record_narrative_invalidation(
            _event(workflow_node="corpus_retrieval"), invalidated_at="2026-08-22T12:00:00Z"
        )


def test_record_narrative_invalidation_unknown_session_raises(
    repository: SessionRepository,
) -> None:
    with pytest.raises(UnknownSessionError):
        repository.record_narrative_invalidation(
            _event(workflow_node="narrative_invalidated", session_id="does-not-exist"),
            invalidated_at="2026-08-22T12:00:00Z",
        )


def test_supersede_session_moves_status_and_appends_event(repository: SessionRepository) -> None:
    repository.create_session(_session(status=SessionStatus.COMPLETED))
    event = _event(
        event_id="supersede-1",
        workflow_node="answer_superseded",
        executor_type="deterministic_policy",
        notes="superseded_by=session-2",
    )

    repository.supersede_session(event, updated_at="2026-08-22T14:00:00Z")

    fetched = repository.get_session("session-1")
    assert fetched is not None
    assert fetched.status == SessionStatus.SUPERSEDED
    assert fetched.updated_at == "2026-08-22T14:00:00Z"
    events = repository.list_events("session-1")
    assert [event.event_id for event in events] == ["supersede-1"]


def test_supersede_session_requires_completed_status(repository: SessionRepository) -> None:
    repository.create_session(_session(status=SessionStatus.BLOCKED))

    with pytest.raises(SessionNotSupersedableError):
        repository.supersede_session(
            _event(workflow_node="answer_superseded"), updated_at="2026-08-22T14:00:00Z"
        )


def test_supersede_session_twice_raises(repository: SessionRepository) -> None:
    repository.create_session(_session(status=SessionStatus.COMPLETED))
    repository.supersede_session(
        _event(event_id="supersede-1", workflow_node="answer_superseded"),
        updated_at="2026-08-22T14:00:00Z",
    )

    with pytest.raises(SessionNotSupersedableError):
        repository.supersede_session(
            _event(event_id="supersede-2", workflow_node="answer_superseded"),
            updated_at="2026-08-22T15:00:00Z",
        )


def test_supersede_session_wrong_workflow_node_raises(repository: SessionRepository) -> None:
    repository.create_session(_session(status=SessionStatus.COMPLETED))

    with pytest.raises(ValueError, match="answer_superseded"):
        repository.supersede_session(
            _event(workflow_node="corpus_retrieval"), updated_at="2026-08-22T14:00:00Z"
        )


def test_supersede_session_unknown_session_raises(repository: SessionRepository) -> None:
    with pytest.raises(UnknownSessionError):
        repository.supersede_session(
            _event(workflow_node="answer_superseded", session_id="does-not-exist"),
            updated_at="2026-08-22T14:00:00Z",
        )


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


def test_opening_a_pre_migration_database_adds_the_research_question_id_column(
    tmp_path: Path,
) -> None:
    """A database created before `research_question_id` existed must still open.

    `CREATE TABLE IF NOT EXISTS` in `_SCHEMA` is a no-op against a table that
    already exists, so a database file created by an older version of this
    repository (one without `research_question_id` in `research_sessions`)
    would otherwise fail every `create_session`/`get_session` call with
    `sqlite3.OperationalError: no column named research_question_id`.
    """

    database_path = f"{tmp_path}/pre_migration.sqlite3"
    pre_migration_connection = new_connection(database_path)
    pre_migration_connection.execute(
        """
        CREATE TABLE research_sessions (
            session_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_question_original TEXT NOT NULL,
            status TEXT NOT NULL,
            normalized_question TEXT,
            domain_hints TEXT NOT NULL,
            research_plan_id TEXT,
            corpus_snapshot_id TEXT,
            evidence_cutoff_time TEXT,
            final_status TEXT
        )
        """
    )
    pre_migration_connection.commit()
    pre_migration_connection.close()

    migrated_connection = new_connection(database_path)
    repository = SessionRepository(migrated_connection)

    session = _session(domain_hints=("clinical_medicine",), research_question_id="rq-abc")
    repository.create_session(session)

    assert repository.get_session("session-1") == session

    migrated_connection.close()


def test_opening_a_pre_versioning_database_adds_the_versioning_columns(
    tmp_path: Path,
) -> None:
    """A database created before answer_version/supersedes_session_id/

    narrative_invalidated_at existed must still open, with answer_version
    defaulting to 1 (matching a thread's first version) for pre-existing
    rows and the other two columns defaulting to NULL.
    """

    database_path = f"{tmp_path}/pre_versioning.sqlite3"
    pre_migration_connection = new_connection(database_path)
    pre_migration_connection.execute(
        """
        CREATE TABLE research_sessions (
            session_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_question_original TEXT NOT NULL,
            status TEXT NOT NULL,
            normalized_question TEXT,
            domain_hints TEXT NOT NULL,
            research_plan_id TEXT,
            corpus_snapshot_id TEXT,
            evidence_cutoff_time TEXT,
            final_status TEXT,
            research_question_id TEXT
        )
        """
    )
    pre_migration_connection.execute(
        """
        INSERT INTO research_sessions (
            session_id, schema_version, created_at, updated_at,
            user_question_original, status, domain_hints
        ) VALUES ('pre-existing', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z',
                  'Old question', 'completed', '[]')
        """
    )
    pre_migration_connection.commit()
    pre_migration_connection.close()

    migrated_connection = new_connection(database_path)
    repository = SessionRepository(migrated_connection)

    fetched = repository.get_session("pre-existing")
    assert fetched is not None
    assert fetched.answer_version == 1
    assert fetched.supersedes_session_id is None
    assert fetched.narrative_invalidated_at is None

    migrated_connection.close()


def test_source_dois_round_trips_alongside_source_ids(repository: SessionRepository) -> None:
    repository.create_session(_session())
    repository.append_event(_event(source_ids=("ev-1", "ev-2"), source_dois=("10.1/a", "10.1/b")))

    (event,) = repository.list_events("session-1")

    assert event.source_ids == ("ev-1", "ev-2")
    assert event.source_dois == ("10.1/a", "10.1/b")


def test_source_dois_defaults_to_empty(repository: SessionRepository) -> None:
    repository.create_session(_session())
    repository.append_event(_event(source_ids=("ev-1",)))

    (event,) = repository.list_events("session-1")

    assert event.source_ids == ("ev-1",)
    assert event.source_dois == ()


def test_opening_a_pre_source_dois_database_adds_the_column(tmp_path: Path) -> None:
    """A database created before `source_dois` existed must still open.

    Old `research_events` rows get `source_dois = '[]'` from the guarded
    `ALTER TABLE ... DEFAULT '[]'` migration -- an empty tuple on read,
    matching "DOI unknown for this old record," not a fabricated value.
    """

    database_path = f"{tmp_path}/pre_source_dois.sqlite3"
    pre_migration_connection = new_connection(database_path)
    pre_migration_connection.execute(
        """
        CREATE TABLE research_sessions (
            session_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_question_original TEXT NOT NULL,
            status TEXT NOT NULL,
            normalized_question TEXT,
            domain_hints TEXT NOT NULL,
            research_plan_id TEXT,
            corpus_snapshot_id TEXT,
            evidence_cutoff_time TEXT,
            final_status TEXT
        )
        """
    )
    pre_migration_connection.execute(
        """
        CREATE TABLE research_events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES research_sessions(session_id),
            sequence_number INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            workflow_node TEXT NOT NULL,
            executor_type TEXT NOT NULL,
            validation_status TEXT,
            output_schema_version INTEGER,
            output_hash TEXT,
            inputs_hash TEXT,
            model_name TEXT,
            model_version TEXT,
            prompt_template_version TEXT,
            tool_name TEXT,
            tool_version TEXT,
            source_ids TEXT NOT NULL,
            parent_event_ids TEXT NOT NULL,
            retry_of TEXT,
            notes TEXT,
            duration_ms INTEGER
        )
        """
    )
    pre_migration_connection.execute(
        """
        INSERT INTO research_sessions (
            session_id, schema_version, created_at, updated_at,
            user_question_original, status, domain_hints
        ) VALUES ('pre-existing', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z',
                  'Old question', 'completed', '[]')
        """
    )
    pre_migration_connection.execute(
        """
        INSERT INTO research_events (
            event_id, session_id, sequence_number, timestamp, workflow_node,
            executor_type, source_ids, parent_event_ids
        ) VALUES ('e-old', 'pre-existing', 1, '2026-01-01T00:00:01Z', 'retrieval',
                  'deterministic', '["ev-old"]', '[]')
        """
    )
    pre_migration_connection.commit()
    pre_migration_connection.close()

    migrated_connection = new_connection(database_path)
    repository = SessionRepository(migrated_connection)

    (event,) = repository.list_events("pre-existing")
    assert event.source_ids == ("ev-old",)
    assert event.source_dois == ()

    migrated_connection.close()
