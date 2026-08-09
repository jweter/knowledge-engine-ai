from __future__ import annotations

from knowledge_engine_ai.sessions.models import SessionStatus, is_terminal_status


def test_terminal_statuses_are_exactly_completed_failed_cancelled_superseded() -> None:
    terminal = {status for status in SessionStatus if is_terminal_status(status)}
    assert terminal == {
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
        SessionStatus.SUPERSEDED,
    }


def test_non_terminal_statuses_are_not_terminal() -> None:
    for status in (
        SessionStatus.PENDING,
        SessionStatus.RUNNING,
        SessionStatus.BLOCKED,
        SessionStatus.AWAITING_INPUT,
        SessionStatus.AWAITING_APPROVAL,
    ):
        assert not is_terminal_status(status)
