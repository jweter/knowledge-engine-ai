"""Deterministic Research ISA close gate for durable research sessions.

A model or synthesis step may propose that work is finished, but a session only
moves to ``completed`` when every required Ideal State criterion has a latest
probe result of ``passed``. Failed, blocked, pending, or missing required probes
keep the session open and make the unresolved criteria explicit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from knowledge_engine_ai.copilot.intent import ISAValidationResult, evaluate_isa_close_gate
from knowledge_engine_ai.sessions.models import ResearchEvent, SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, UnknownISAError

_CLOSE_GATE_NODE = "research_isa_close_gate"
_EXECUTOR_TYPE = "deterministic_policy"


@dataclass(frozen=True)
class SessionCloseResult:
    """Observable result of one deterministic close-gate attempt."""

    session_id: str
    status: SessionStatus
    validation: ISAValidationResult


def attempt_session_close(
    session_repository: SessionRepository,
    *,
    session_id: str,
    timestamp: str | None = None,
) -> SessionCloseResult:
    """Evaluate the attached ISA and update session lifecycle state.

    Completion is fail-closed: no attached ISA means the operation raises;
    incomplete required criteria move the session to ``blocked`` rather than
    silently treating model output as complete. The close-gate decision is also
    appended to the normal ResearchEvent ledger so the lifecycle transition is
    auditable and resumable.
    """

    isa = session_repository.get_research_isa(session_id)
    if isa is None:
        # Preserve the repository's distinction between a real session with no
        # ISA and an unknown session.
        session = session_repository.get_session(session_id)
        if session is None:
            session_repository.update_session_status(
                session_id,
                SessionStatus.BLOCKED,
                updated_at=_timestamp(timestamp),
            )
        raise UnknownISAError(f"Session {session_id!r} has no attached Research ISA.")

    results = session_repository.latest_criterion_results(session_id)
    validation = evaluate_isa_close_gate(isa, results)
    status = SessionStatus.COMPLETED if validation.complete else SessionStatus.BLOCKED
    occurred_at = _timestamp(timestamp)

    session_repository.update_session_status(session_id, status, updated_at=occurred_at)
    session_repository.append_event(
        ResearchEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=occurred_at,
            workflow_node=_CLOSE_GATE_NODE,
            executor_type=_EXECUTOR_TYPE,
            validation_status="passed" if validation.complete else "blocked",
            notes=(
                "All required Research ISA criteria passed."
                if validation.complete
                else "Unresolved required criteria: "
                + ", ".join(validation.unresolved_required_criteria)
            ),
        )
    )

    return SessionCloseResult(
        session_id=session_id,
        status=status,
        validation=validation,
    )


def _timestamp(value: str | None) -> str:
    if value is not None:
        return value
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["SessionCloseResult", "attempt_session_close"]
