from __future__ import annotations

import math

import pytest

from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan])
def test_execution_budget_rejects_invalid_timeouts(value: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        ExecutionBudget.from_timeout(value)


def test_execution_budget_fails_after_its_deadline() -> None:
    budget = ExecutionBudget(deadline_monotonic=0.0)

    with pytest.raises(ExecutionBudgetExceeded, match="execution time limit"):
        budget.remaining_seconds()
