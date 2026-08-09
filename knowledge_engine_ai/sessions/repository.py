"""AI-O2: SQLite-backed persistence for `ResearchSession`/`ResearchEvent`.

This is the concrete piece that makes AI-O2's success criterion real:
"a workflow can stop and resume without losing or duplicating state."
Two guarantees back that claim, both enforced by the database itself
rather than caller discipline:

- `create_session` raises `DuplicateSessionError` on a re-used
  `session_id` -- a resuming caller must explicitly `get_session`
  first and branch, the same "no implicit chat-order state" discipline
  the design doc's BLOCK 10 requires, rather than this module silently
  guessing whether a second `create_session` call means "resume" or
  "a real bug."
- `append_event` raises `DuplicateEventError` on a re-used `event_id`
  -- an orchestrator that does not know whether a step already ran
  (the exact situation a crash-and-resume leaves it in) gets an
  unambiguous signal instead of a silent duplicate insert.

No orchestrator, no LLM call, and no real workflow node calls this
module yet -- AI-O3 connects it to actual retrieval/Evidence
Intelligence/statistics capabilities.
"""

from __future__ import annotations

import json
import sqlite3

from knowledge_engine_ai.sessions.models import (
    SUPPORTED_RESEARCH_SESSION_SCHEMA_VERSION,
    ResearchEvent,
    ResearchSession,
    SessionStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_sessions (
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
);

CREATE TABLE IF NOT EXISTS research_events (
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
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_events_session_sequence
    ON research_events(session_id, sequence_number);
"""


class DuplicateSessionError(RuntimeError):
    """`create_session` was called with a `session_id` that already exists."""


class DuplicateEventError(RuntimeError):
    """`append_event` was called with an `event_id` that already exists."""


class UnknownSessionError(RuntimeError):
    """An event referenced a `session_id` with no matching `ResearchSession`."""


class SessionRepository:
    """SQLite-backed store for `ResearchSession`/`ResearchEvent`.

    Takes an already-open `sqlite3.Connection` rather than a path, so
    tests can use `sqlite3.connect(":memory:")` and a future caller can
    reuse a connection this package does not own the lifecycle of --
    the same dependency-injection shape `knowledge_engine.database`
    uses in `core`.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def create_session(self, session: ResearchSession) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO research_sessions (
                    session_id, schema_version, created_at, updated_at,
                    user_question_original, status, normalized_question,
                    domain_hints, research_plan_id, corpus_snapshot_id,
                    evidence_cutoff_time, final_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.schema_version,
                    session.created_at,
                    session.updated_at,
                    session.user_question_original,
                    session.status.value,
                    session.normalized_question,
                    json.dumps(list(session.domain_hints)),
                    session.research_plan_id,
                    session.corpus_snapshot_id,
                    session.evidence_cutoff_time,
                    session.final_status,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateSessionError(
                f"A session with session_id {session.session_id!r} already exists."
            ) from exc
        self._connection.commit()

    def get_session(self, session_id: str) -> ResearchSession | None:
        row = self._connection.execute(
            "SELECT * FROM research_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return _session_from_row(row)

    def update_session_status(
        self, session_id: str, status: SessionStatus, *, updated_at: str
    ) -> None:
        cursor = self._connection.execute(
            "UPDATE research_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (status.value, updated_at, session_id),
        )
        if cursor.rowcount == 0:
            raise UnknownSessionError(f"No session with session_id {session_id!r}.")
        self._connection.commit()

    def append_event(self, event: ResearchEvent) -> None:
        session_row = self._connection.execute(
            "SELECT 1 FROM research_sessions WHERE session_id = ?", (event.session_id,)
        ).fetchone()
        if session_row is None:
            raise UnknownSessionError(f"No session with session_id {event.session_id!r}.")

        next_sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM research_events "
            "WHERE session_id = ?",
            (event.session_id,),
        ).fetchone()[0]

        try:
            self._connection.execute(
                """
                INSERT INTO research_events (
                    event_id, session_id, sequence_number, timestamp, workflow_node,
                    executor_type, validation_status, output_schema_version, output_hash,
                    inputs_hash, model_name, model_version, prompt_template_version,
                    tool_name, tool_version, source_ids, parent_event_ids, retry_of, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.session_id,
                    next_sequence,
                    event.timestamp,
                    event.workflow_node,
                    event.executor_type,
                    event.validation_status,
                    event.output_schema_version,
                    event.output_hash,
                    event.inputs_hash,
                    event.model_name,
                    event.model_version,
                    event.prompt_template_version,
                    event.tool_name,
                    event.tool_version,
                    json.dumps(list(event.source_ids)),
                    json.dumps(list(event.parent_event_ids)),
                    event.retry_of,
                    event.notes,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEventError(
                f"An event with event_id {event.event_id!r} already exists."
            ) from exc
        self._connection.commit()

    def has_event(self, event_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM research_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row is not None

    def list_events(self, session_id: str) -> list[ResearchEvent]:
        rows = self._connection.execute(
            "SELECT * FROM research_events WHERE session_id = ? ORDER BY sequence_number",
            (session_id,),
        ).fetchall()
        return [_event_from_row(row) for row in rows]


def _session_from_row(row: sqlite3.Row) -> ResearchSession:
    return ResearchSession(
        schema_version=row["schema_version"],
        session_id=row["session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        user_question_original=row["user_question_original"],
        status=SessionStatus(row["status"]),
        normalized_question=row["normalized_question"],
        domain_hints=tuple(json.loads(row["domain_hints"])),
        research_plan_id=row["research_plan_id"],
        corpus_snapshot_id=row["corpus_snapshot_id"],
        evidence_cutoff_time=row["evidence_cutoff_time"],
        final_status=row["final_status"],
    )


def _event_from_row(row: sqlite3.Row) -> ResearchEvent:
    return ResearchEvent(
        event_id=row["event_id"],
        session_id=row["session_id"],
        timestamp=row["timestamp"],
        workflow_node=row["workflow_node"],
        executor_type=row["executor_type"],
        validation_status=row["validation_status"],
        output_schema_version=row["output_schema_version"],
        output_hash=row["output_hash"],
        inputs_hash=row["inputs_hash"],
        model_name=row["model_name"],
        model_version=row["model_version"],
        prompt_template_version=row["prompt_template_version"],
        tool_name=row["tool_name"],
        tool_version=row["tool_version"],
        source_ids=tuple(json.loads(row["source_ids"])),
        parent_event_ids=tuple(json.loads(row["parent_event_ids"])),
        retry_of=row["retry_of"],
        notes=row["notes"],
    )


def new_connection(database_path: str) -> sqlite3.Connection:
    """Open a `sqlite3.Connection` with `row_factory` set for this module's row-parsing helpers.

    `database_path` may be a filesystem path or `":memory:"`. Does not
    call `SessionRepository` itself -- callers construct one from the
    returned connection, matching the dependency-injection shape
    documented on `SessionRepository`.
    """

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


__all__ = [
    "SUPPORTED_RESEARCH_SESSION_SCHEMA_VERSION",
    "DuplicateEventError",
    "DuplicateSessionError",
    "SessionRepository",
    "UnknownSessionError",
    "new_connection",
]
