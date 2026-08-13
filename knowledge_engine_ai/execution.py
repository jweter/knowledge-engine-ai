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


__all__ = ["ExecutionBudget", "ExecutionBudgetExceeded"]
