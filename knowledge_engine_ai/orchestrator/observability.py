"""AI-O9: assemble one session's event log into an answer to six fixed questions.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O9 milestone: "Add
workflow tracing and resource metrics. Success criterion: every session
can answer what ran, why, what model/tool was used, where time was
spent, what failed, and what evidence supported the output." See
`docs/ai_o9_design.md` for the full plan this module implements.

AI-O2 already built the durable, append-only event log
(`sessions.models.ResearchEvent`) every workflow step writes to; this
module is a pure read-side projection over that log, not a new store.
`build_session_trace` never queries anything itself -- `events` is
passed in, already fetched via `SessionRepository.list_events`, the
same "caller owns the repository call" boundary `workflow.py` already
follows.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession


@dataclass(frozen=True)
class EventTrace:
    """One `ResearchEvent`, projected into the shape a trace report needs."""

    event_id: str
    workflow_node: str
    executor_type: str
    tool_name: str | None
    model_name: str | None
    succeeded: bool
    duration_ms: int | None
    notes: str | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class SessionTrace:
    """One session's full event log, assembled into the six-question answer."""

    session_id: str
    question: str
    events: tuple[EventTrace, ...]
    failed_events: tuple[EventTrace, ...]
    total_duration_ms: int | None
    evidence_record_ids: tuple[str, ...]

    @property
    def all_succeeded(self) -> bool:
        """True only when no event in this session failed."""

        return not self.failed_events


def build_session_trace(
    session: ResearchSession, events: tuple[ResearchEvent, ...]
) -> SessionTrace:
    """Project `session` and its event log into a `SessionTrace`.

    `total_duration_ms` sums every event's `duration_ms` that is not
    `None` -- an event with no recorded duration is excluded from the
    sum, not treated as zero, so a session with some untimed events
    still reports an honest partial total. `evidence_record_ids` is the
    deduplicated union of every event's `source_ids`, in order of first
    appearance.
    """

    event_traces = tuple(
        EventTrace(
            event_id=event.event_id,
            workflow_node=event.workflow_node,
            executor_type=event.executor_type,
            tool_name=event.tool_name,
            model_name=event.model_name,
            succeeded=event.validation_status != "failed",
            duration_ms=event.duration_ms,
            notes=event.notes,
            source_ids=event.source_ids,
        )
        for event in events
    )

    known_durations = [trace.duration_ms for trace in event_traces if trace.duration_ms is not None]
    total_duration_ms = sum(known_durations) if known_durations else None

    evidence_record_ids = tuple(
        dict.fromkeys(
            evidence_record_id for trace in event_traces for evidence_record_id in trace.source_ids
        )
    )

    return SessionTrace(
        session_id=session.session_id,
        question=session.user_question_original,
        events=event_traces,
        failed_events=tuple(trace for trace in event_traces if not trace.succeeded),
        total_duration_ms=total_duration_ms,
        evidence_record_ids=evidence_record_ids,
    )


def render_session_trace(trace: SessionTrace) -> str:
    """Render `trace` as plain text answering AI-O9's six success-criterion questions."""

    lines = [
        f"Session {trace.session_id}",
        "",
        f"Why: {trace.question}",
        "",
        "What ran:",
    ]
    for event in trace.events:
        status = "succeeded" if event.succeeded else "FAILED"
        lines.append(f"  - {event.workflow_node} [{status}]")

    lines += ["", "What model/tool was used:"]
    for event in trace.events:
        used = event.model_name or event.tool_name or "(none recorded)"
        lines.append(f"  - {event.workflow_node}: {used}")

    lines += ["", "Where time was spent:"]
    for event in trace.events:
        duration = f"{event.duration_ms}ms" if event.duration_ms is not None else "(not timed)"
        lines.append(f"  - {event.workflow_node}: {duration}")
    total = f"{trace.total_duration_ms}ms" if trace.total_duration_ms is not None else "(unknown)"
    lines.append(f"  Total (known durations only): {total}")

    lines += ["", "What failed:"]
    if trace.failed_events:
        for event in trace.failed_events:
            lines.append(f"  - {event.workflow_node}: {event.notes or '(no detail recorded)'}")
    else:
        lines.append("  (nothing failed)")

    lines += ["", "What evidence supported the output:"]
    if trace.evidence_record_ids:
        for evidence_record_id in trace.evidence_record_ids:
            lines.append(f"  - {evidence_record_id}")
    else:
        lines.append("  (no evidence-record IDs recorded on any event)")

    return "\n".join(lines)


__all__ = [
    "EventTrace",
    "SessionTrace",
    "build_session_trace",
    "render_session_trace",
]
