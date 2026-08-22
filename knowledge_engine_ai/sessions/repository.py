"""SQLite-backed persistence for durable Research Copilot workflow state.

The session/event store remains append-oriented: sessions are durable headers,
important workflow actions are immutable ``ResearchEvent`` rows, and the
LifeOS-inspired Research ISA is attached as a typed run contract rather than
buried in chat transcript or model prose.

ISA criterion results are append-only observations. When the same probe runs
again, a new row is recorded; callers evaluate the latest observation for each
criterion. This preserves the history needed to explain why a previously
blocked run later became closable.
"""

from __future__ import annotations

import json
import sqlite3

from knowledge_engine_ai.copilot.intent import (
    CriterionResult,
    CriterionStatus,
    IdealStateCriterion,
    ResearchISA,
)
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
    final_status TEXT,
    research_question_id TEXT,
    answer_version INTEGER NOT NULL DEFAULT 1,
    supersedes_session_id TEXT,
    narrative_invalidated_at TEXT
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
    source_dois TEXT NOT NULL DEFAULT '[]',
    parent_event_ids TEXT NOT NULL,
    retry_of TEXT,
    notes TEXT,
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_research_events_session_sequence
    ON research_events(session_id, sequence_number);

CREATE TABLE IF NOT EXISTS research_isas (
    session_id TEXT PRIMARY KEY REFERENCES research_sessions(session_id),
    run_id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    question TEXT NOT NULL,
    ideal_state TEXT NOT NULL,
    known_json TEXT NOT NULL,
    unknown_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    criteria_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_isa_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES research_sessions(session_id),
    criterion_id TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_isa_results_session_criterion
    ON research_isa_results(session_id, criterion_id, result_id);
"""


class DuplicateSessionError(RuntimeError):
    """``create_session`` was called with a ``session_id`` that already exists."""


class DuplicateEventError(RuntimeError):
    """``append_event`` was called with an ``event_id`` that already exists."""


class DuplicateISAError(RuntimeError):
    """A session already has an attached immutable Research ISA."""


class UnknownSessionError(RuntimeError):
    """An operation referenced a ``session_id`` with no matching session."""


class UnknownISAError(RuntimeError):
    """An ISA-result operation referenced a session with no attached ISA."""


class NarrativeAlreadyInvalidatedError(RuntimeError):
    """``record_narrative_invalidation`` was called on an already-invalidated session.

    ``narrative_invalidated_at`` is set at most once per
    `docs/roadmap/answer_session_versioning_design.md`'s "set once, the
    moment an invalidating flip crosswalks to a citation" rule.
    """


class SessionNotSupersedableError(RuntimeError):
    """``supersede_session`` was called on a session that is not ``COMPLETED``.

    Per the design doc, a session is only ever moved to ``SUPERSEDED`` once
    its replacement itself reaches ``COMPLETED`` -- and only a session that
    was itself ``COMPLETED`` (a released answer) is a meaningful subject for
    supersession in the first place.
    """


class SessionRepository:
    """SQLite-backed store for session, event, and Research ISA state."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_SCHEMA)
        self._migrate_schema()
        self._connection.commit()

    def _migrate_schema(self) -> None:
        """Add columns to pre-existing databases that predate them.

        ``CREATE TABLE IF NOT EXISTS`` in ``_SCHEMA`` is a no-op against a
        table that already exists, so a column added there is invisible to
        any database created before that change. Each entry here is an
        idempotent, guarded ``ALTER TABLE`` for exactly such a column.
        """

        existing_columns = {
            row["name"] for row in self._connection.execute("PRAGMA table_info(research_sessions)")
        }
        if "research_question_id" not in existing_columns:
            self._connection.execute(
                "ALTER TABLE research_sessions ADD COLUMN research_question_id TEXT"
            )
        if "answer_version" not in existing_columns:
            self._connection.execute(
                "ALTER TABLE research_sessions ADD COLUMN answer_version INTEGER NOT NULL DEFAULT 1"
            )
        if "supersedes_session_id" not in existing_columns:
            self._connection.execute(
                "ALTER TABLE research_sessions ADD COLUMN supersedes_session_id TEXT"
            )
        if "narrative_invalidated_at" not in existing_columns:
            self._connection.execute(
                "ALTER TABLE research_sessions ADD COLUMN narrative_invalidated_at TEXT"
            )

        existing_event_columns = {
            row["name"] for row in self._connection.execute("PRAGMA table_info(research_events)")
        }
        if "source_dois" not in existing_event_columns:
            self._connection.execute(
                "ALTER TABLE research_events ADD COLUMN source_dois TEXT NOT NULL DEFAULT '[]'"
            )

    def create_session(self, session: ResearchSession) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO research_sessions (
                    session_id, schema_version, created_at, updated_at,
                    user_question_original, status, normalized_question,
                    domain_hints, research_plan_id, corpus_snapshot_id,
                    evidence_cutoff_time, final_status, research_question_id,
                    answer_version, supersedes_session_id, narrative_invalidated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    session.research_question_id,
                    session.answer_version,
                    session.supersedes_session_id,
                    session.narrative_invalidated_at,
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

    def list_sessions_for_research_question(
        self, research_question_id: str
    ) -> list[ResearchSession]:
        """Every session in one `research_question_id` thread, oldest `answer_version` first.

        Supports the `AnswerFreshness` read-side projection's
        `superseded_by_session_id` field
        (`copilot/research_freshness.py`): `ResearchSession` only stores a
        version's *own* `supersedes_session_id` (the version it replaces),
        never a forward pointer to whatever replaced it, so finding "what
        superseded this session, if anything" requires looking at every
        other session in the same thread and checking which one, if any,
        names this session as its `supersedes_session_id` -- exactly what
        this method's result lets a caller do without inventing a second
        mutable pointer field that could drift from the one already
        written at `create_session` time.

        Returns an empty list for an unknown or never-used
        `research_question_id`, the same "absent is not an error" posture
        `get_session` returning `None` already establishes -- this is a
        listing, not a lookup with an expected single result.
        """

        rows = self._connection.execute(
            "SELECT * FROM research_sessions WHERE research_question_id = ? "
            "ORDER BY answer_version ASC, created_at ASC",
            (research_question_id,),
        ).fetchall()
        return [_session_from_row(row) for row in rows]

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

    def record_narrative_invalidation(self, event: ResearchEvent, *, invalidated_at: str) -> None:
        """Append an ``narrative_invalidated`` event and set the session's flag, once.

        Implements `docs/roadmap/answer_session_versioning_design.md`'s
        "Releaseability reacts to an invalidating flip immediately" rule: the
        moment an **invalidating** (``retracted``/``withdrawn``) publication-
        status flip is found to touch a session's own cited narrative,
        ``S.narrative_invalidated_at`` is set -- independent of ``status``,
        which stays exactly as it was (never flipped to ``BLOCKED`` or
        ``SUPERSEDED`` by this call alone).

        Deliberately does not decide *when* this should be called -- that is
        the crosswalk/trigger-policy work the design doc's "What this does
        not do" section names as still open. This method only makes the
        mechanism itself durable and safe to call.
        """

        if event.workflow_node != "narrative_invalidated":
            raise ValueError(
                "record_narrative_invalidation requires an event with "
                f"workflow_node='narrative_invalidated', got {event.workflow_node!r}."
            )

        session = self.get_session(event.session_id)
        if session is None:
            raise UnknownSessionError(f"No session with session_id {event.session_id!r}.")
        if session.narrative_invalidated_at is not None:
            raise NarrativeAlreadyInvalidatedError(
                f"Session {event.session_id!r} already has narrative_invalidated_at="
                f"{session.narrative_invalidated_at!r}; it is set at most once."
            )

        self.append_event(event)
        self._connection.execute(
            "UPDATE research_sessions SET narrative_invalidated_at = ? WHERE session_id = ?",
            (invalidated_at, event.session_id),
        )
        self._connection.commit()

    def supersede_session(self, event: ResearchEvent, *, updated_at: str) -> None:
        """Append an ``answer_superseded`` event and move the session to ``SUPERSEDED``.

        Per the design doc, this is only ever called once a *replacement*
        session for the same ``research_question_id`` thread has itself
        reached ``COMPLETED`` -- ``event.session_id`` here is the *prior*
        version being superseded, not the new one. Requires the superseded
        session's current status to be ``COMPLETED``: a session that was
        never released (``BLOCKED``) is not a meaningful subject for
        supersession, and a session already ``SUPERSEDED`` cannot be
        superseded again.
        """

        if event.workflow_node != "answer_superseded":
            raise ValueError(
                "supersede_session requires an event with "
                f"workflow_node='answer_superseded', got {event.workflow_node!r}."
            )

        session = self.get_session(event.session_id)
        if session is None:
            raise UnknownSessionError(f"No session with session_id {event.session_id!r}.")
        if session.status is not SessionStatus.COMPLETED:
            raise SessionNotSupersedableError(
                f"Session {event.session_id!r} has status {session.status.value!r}; "
                "only a COMPLETED session can be superseded."
            )

        self.append_event(event)
        self.update_session_status(
            event.session_id, SessionStatus.SUPERSEDED, updated_at=updated_at
        )

    def attach_research_isa(self, session_id: str, isa: ResearchISA) -> None:
        """Attach one immutable task-level definition of done to a session.

        The ISA is intentionally write-once. If the research objective changes
        materially, create a new run/session rather than rewriting the original
        completion contract and erasing what the run was originally asked to do.
        """

        self._require_session(session_id)
        try:
            self._connection.execute(
                """
                INSERT INTO research_isas (
                    session_id, run_id, schema_version, question, ideal_state,
                    known_json, unknown_json, constraints_json, criteria_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    isa.run_id,
                    isa.schema_version,
                    isa.question,
                    isa.ideal_state,
                    json.dumps(list(isa.known)),
                    json.dumps(list(isa.unknown)),
                    json.dumps(list(isa.constraints)),
                    json.dumps(
                        [
                            {
                                "criterion_id": criterion.criterion_id,
                                "claim": criterion.claim,
                                "probe": criterion.probe,
                                "required": criterion.required,
                            }
                            for criterion in isa.criteria
                        ],
                        sort_keys=True,
                    ),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateISAError(
                f"Session {session_id!r} already has an ISA or run_id {isa.run_id!r} is in use."
            ) from exc
        self._connection.commit()

    def get_research_isa(self, session_id: str) -> ResearchISA | None:
        row = self._connection.execute(
            "SELECT * FROM research_isas WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return _isa_from_row(row)

    def record_criterion_result(
        self,
        session_id: str,
        result: CriterionResult,
        *,
        recorded_at: str,
    ) -> None:
        """Append one evidence-bearing probe observation for an attached ISA."""

        isa = self.get_research_isa(session_id)
        if isa is None:
            self._require_session(session_id)
            raise UnknownISAError(f"Session {session_id!r} has no attached Research ISA.")

        criterion_ids = {criterion.criterion_id for criterion in isa.criteria}
        if result.criterion_id not in criterion_ids:
            raise ValueError(
                f"Unknown criterion_id {result.criterion_id!r} for session {session_id!r}."
            )

        self._connection.execute(
            """
            INSERT INTO research_isa_results (
                session_id, criterion_id, status, evidence, recorded_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                result.criterion_id,
                result.status.value,
                result.evidence,
                recorded_at,
            ),
        )
        self._connection.commit()

    def latest_criterion_results(self, session_id: str) -> tuple[CriterionResult, ...]:
        """Return the latest append-only observation for each ISA criterion."""

        rows = self._connection.execute(
            """
            SELECT r.criterion_id, r.status, r.evidence
            FROM research_isa_results AS r
            JOIN (
                SELECT criterion_id, MAX(result_id) AS max_result_id
                FROM research_isa_results
                WHERE session_id = ?
                GROUP BY criterion_id
            ) AS latest ON latest.max_result_id = r.result_id
            WHERE r.session_id = ?
            ORDER BY r.result_id
            """,
            (session_id, session_id),
        ).fetchall()
        return tuple(
            CriterionResult(
                criterion_id=row["criterion_id"],
                status=CriterionStatus(row["status"]),
                evidence=row["evidence"],
            )
            for row in rows
        )

    def append_event(self, event: ResearchEvent) -> None:
        self._require_session(event.session_id)

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
                    tool_name, tool_version, source_ids, source_dois, parent_event_ids,
                    retry_of, notes, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(list(event.source_dois)),
                    json.dumps(list(event.parent_event_ids)),
                    event.retry_of,
                    event.notes,
                    event.duration_ms,
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

    def _require_session(self, session_id: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM research_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise UnknownSessionError(f"No session with session_id {session_id!r}.")


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
        research_question_id=row["research_question_id"],
        answer_version=row["answer_version"],
        supersedes_session_id=row["supersedes_session_id"],
        narrative_invalidated_at=row["narrative_invalidated_at"],
    )


def _isa_from_row(row: sqlite3.Row) -> ResearchISA:
    criteria_payload = json.loads(row["criteria_json"])
    return ResearchISA(
        schema_version=row["schema_version"],
        run_id=row["run_id"],
        question=row["question"],
        ideal_state=row["ideal_state"],
        known=tuple(json.loads(row["known_json"])),
        unknown=tuple(json.loads(row["unknown_json"])),
        constraints=tuple(json.loads(row["constraints_json"])),
        criteria=tuple(
            IdealStateCriterion(
                criterion_id=item["criterion_id"],
                claim=item["claim"],
                probe=item["probe"],
                required=bool(item["required"]),
            )
            for item in criteria_payload
        ),
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
        source_dois=tuple(json.loads(row["source_dois"])),
        parent_event_ids=tuple(json.loads(row["parent_event_ids"])),
        retry_of=row["retry_of"],
        notes=row["notes"],
        duration_ms=row["duration_ms"],
    )


def new_connection(database_path: str) -> sqlite3.Connection:
    """Open a connection configured for this repository's row parsers."""

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


__all__ = [
    "SUPPORTED_RESEARCH_SESSION_SCHEMA_VERSION",
    "DuplicateEventError",
    "DuplicateISAError",
    "DuplicateSessionError",
    "NarrativeAlreadyInvalidatedError",
    "SessionNotSupersedableError",
    "SessionRepository",
    "UnknownISAError",
    "UnknownSessionError",
    "new_connection",
]
