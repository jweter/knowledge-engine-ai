"""Shared wall-clock budget for one composed Research Copilot run."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass


class ExecutionBudgetExceeded(RuntimeError):
    """The configured Research Copilot wall-clock budget is exhausted."""


@dataclass(frozen=True)
class ExecutionBudget:
    """One monotonic deadline shared by every bounded external operation."""

    deadline_monotonic: float

    @classmethod
    def from_timeout(cls, timeout_seconds: float) -> ExecutionBudget:
        """Create a budget ending `timeout_seconds` from now."""

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number.")
        return cls(deadline_monotonic=time.monotonic() + timeout_seconds)

    def remaining_seconds(self) -> float:
        """Return remaining wall-clock time or fail before starting more work."""

        remaining = self.deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise ExecutionBudgetExceeded(
                "Research Copilot exceeded its configured execution time limit."
            )
        return remaining

    def with_reserved_tail(self, reserved_seconds: float) -> ExecutionBudget:
        """Return a budget whose deadline is pulled `reserved_seconds` earlier.

        BT-4 (issue #87): a single shared deadline lets early, optional-breadth
        stages (discovery, acquisition, extraction) consume the entire run's
        wall-clock budget, starving the final synthesis/verification step of any
        time to produce a narrative on a cold or slow run. A caller that wants to
        guarantee synthesis a time floor runs earlier stages against this
        earlier-deadline budget while still running synthesis itself against the
        original, unreserved budget -- so the reserved tail is only ever taken
        away from stages willing to yield it, never added on top of the run's
        configured total timeout.

        `reserved_seconds` may equal or exceed this budget's own remaining time;
        the returned budget then simply expires immediately (or already has), so
        the caller's next `remaining_seconds()` call fails closed exactly like
        any other exhausted budget, rather than through separate handling here.
        """

        if not math.isfinite(reserved_seconds) or reserved_seconds < 0:
            raise ValueError("reserved_seconds must be a finite non-negative number.")
        return ExecutionBudget(deadline_monotonic=self.deadline_monotonic - reserved_seconds)


__all__ = ["ExecutionBudget", "ExecutionBudgetExceeded"]
