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

    `research_question_id` is the thread identity across answer versions of
    the same tracked question -- the same string `ke_client.federated_discover()`/
    `federated_discover_history()` already accept and key on (see
    `docs/roadmap/answer_session_versioning_design.md`). `run_research_question`
    always sets it, to a caller-supplied or deterministically-derived value;
    `None` here only for a session created before this field existed.

    `answer_version`, `supersedes_session_id`, and `narrative_invalidated_at`
    are the remaining three additive fields
    `docs/roadmap/answer_session_versioning_design.md`'s "What 'version'
    means" section describes: a version is one whole `ResearchSession`, never
    a second synthesis event folded into an existing one.

    - `answer_version`: 1-based, monotonic within a `research_question_id`
      thread. Defaults to `1` (the first version of any thread); a caller
      minting version *N+1* sets it to the prior version's `answer_version + 1`
      when constructing the new session.
    - `supersedes_session_id`: the immediately-prior version's `session_id`,
      if this session replaces one. `None` for a thread's first version.
    - `narrative_invalidated_at`: set at most once, via
      `SessionRepository.record_narrative_invalidation`, the moment an
      **invalidating** (`retracted`/`withdrawn`) publication-status flip is
      found to touch this session's own cited narrative -- see
      "Releaseability reacts to an invalidating flip immediately" in the
      design doc. `None` means either nothing invalidating has been detected,
      or (for a session predating this field) the check was never run.
      Deliberately independent of `status`: a session can be
      `narrative_invalidated_at`-set while `status` stays `COMPLETED`, per
      the design doc's two-field releaseability check.

    None of these three fields are written by any code path yet --
    `SessionRepository.record_narrative_invalidation`/`.supersede_session`
    exist and are tested, but nothing calls them: the crosswalk that would
    decide *when* to call them (DOI-matching a flagged federated-discovery
    candidate against this session's own cited evidence records) and the
    policy for *when* a freshness check itself runs remain future work, per
    the design doc's own "What this does not do" section.
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
    research_question_id: str | None = None
    answer_version: int = 1
    supersedes_session_id: str | None = None
    narrative_invalidated_at: str | None = None


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

    `source_dois` is additive (AI-FRD-5's DOI-crosswalk slice,
    `docs/roadmap/answer_session_versioning_design.md`'s "the crosswalk"
    section): for a retrieval-step event, `source_dois[i]` is the DOI of
    the `RetrievedPaper` that `source_ids[i]`'s evidence record came from
    (empty string when that paper carries no DOI), in the same order as
    `source_ids` -- not a separate identity, a same-length parallel to it.
    Only the two retrieval-step events populate it; every other event's
    `source_ids` is already empty, so this stays empty there too. Empty for
    any event persisted before this field existed (old rows parse
    unchanged, matching the `duration_ms`/`research_question_id`
    precedent), which a reader must treat as "DOI unknown," never as "this
    paper genuinely has no DOI."
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
    source_dois: tuple[str, ...] = field(default_factory=tuple)
    parent_event_ids: tuple[str, ...] = field(default_factory=tuple)
    retry_of: str | None = None
    notes: str | None = None
    duration_ms: int | None = None
