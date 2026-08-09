"""AI-O2: `ResearchSession`/`ResearchEvent`, the durable workflow-state contracts.

`docs/roadmap/future_ai_orchestration_plan.md`'s "Durable Research
Workflow State" section sketches a `ResearchSession` with many list
fields (`retrieval_runs[]`, `discovery_runs[]`, `analyses[]`, etc.).
This module deliberately does **not** model those as columns on the
session itself: the same section's own governing rule is "every
important action becomes an append-only or versioned event," which is
exactly what `ResearchEvent` is for. Storing both a mutable list *and*
a duplicate append-only event log for the same information would be
two sources of truth that can drift -- so `ResearchSession` here is
the durable *header* record (identity, timestamps, original question,
status, snapshot references), and everything the sketch's list fields
represent is derived by querying `ResearchEvent` rows for that
`session_id`, the same way `SessionRepository.list_events` returns
them. A future read-side view (AI-O3+) can reconstruct any of those
per-category lists from the event log without this module needing to
change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

SUPPORTED_RESEARCH_SESSION_SCHEMA_VERSION = 1


class SessionStatus(StrEnum):
    """A `ResearchSession`'s lifecycle state.

    Verbatim from the design doc's "Durable Workflow Engine" section's
    suggested states.
    """

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    AWAITING_INPUT = "awaiting_input"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


_TERMINAL_SESSION_STATUSES = frozenset(
    {
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
        SessionStatus.SUPERSEDED,
    }
)


def is_terminal_status(status: SessionStatus) -> bool:
    """True for a status a session cannot resume from (completed/failed/cancelled/superseded)."""

    return status in _TERMINAL_SESSION_STATUSES


@dataclass(frozen=True)
class ResearchSession:
    """A durable, resumable research workflow's header record.

    `session_id` is the caller's identity to persist externally (e.g.
    in their own process or a scheduled follow-up) and pass back to
    `SessionRepository.get_session` on resume -- this module never
    generates one implicitly, matching the design doc's "Chat
    transcript alone is never execution state" rule: some durable
    identifier the caller controls is required to resume at all.
    """

    schema_version: int
    session_id: str
    created_at: str
    updated_at: str
    user_question_original: str
    status: SessionStatus
    normalized_question: str | None = None
    domain_hints: tuple[str, ...] = ()
    research_plan_id: str | None = None
    corpus_snapshot_id: str | None = None
    evidence_cutoff_time: str | None = None
    final_status: str | None = None


@dataclass(frozen=True)
class ResearchEvent:
    """One append-only, immutable record of a workflow node's execution.

    Mirrors the design doc's `ResearchEvent` shape. `retry_of` links a
    retry attempt back to the `event_id` it retried, and
    `parent_event_ids` links an event to the event(s) that produced its
    inputs -- both needed for `docs/roadmap/future_ai_orchestration_plan.md`'s
    BLOCK 10 (non-deterministic research continuation) requirement that
    "chat transcript alone is never execution state" and retries have
    explicit lineage, not implicit chat-order.
    """

    event_id: str
    session_id: str
    timestamp: str
    workflow_node: str
    executor_type: str
    validation_status: str | None = None
    output_schema_version: int | None = None
    output_hash: str | None = None
    inputs_hash: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_template_version: str | None = None
    tool_name: str | None = None
    tool_version: str | None = None
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    parent_event_ids: tuple[str, ...] = field(default_factory=tuple)
    retry_of: str | None = None
    notes: str | None = None
