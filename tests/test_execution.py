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


def test_with_reserved_tail_pulls_the_deadline_earlier() -> None:
    budget = ExecutionBudget.from_timeout(10.0)

    reserved = budget.with_reserved_tail(4.0)

    assert reserved.deadline_monotonic == pytest.approx(budget.deadline_monotonic - 4.0)
    # The original budget is untouched -- reservation only affects the copy.
    assert reserved.remaining_seconds() < budget.remaining_seconds()


def test_with_reserved_tail_of_zero_is_a_no_op() -> None:
    budget = ExecutionBudget.from_timeout(10.0)

    reserved = budget.with_reserved_tail(0.0)

    assert reserved.deadline_monotonic == budget.deadline_monotonic


def test_with_reserved_tail_exceeding_remaining_time_expires_immediately() -> None:
    budget = ExecutionBudget.from_timeout(1.0)

    reserved = budget.with_reserved_tail(5.0)

    with pytest.raises(ExecutionBudgetExceeded, match="execution time limit"):
        reserved.remaining_seconds()
    # The original, unreserved budget is unaffected and still has time left.
    assert budget.remaining_seconds() > 0


@pytest.mark.parametrize("value", [-1.0, math.inf, math.nan])
def test_with_reserved_tail_rejects_invalid_values(value: float) -> None:
    budget = ExecutionBudget.from_timeout(10.0)

    with pytest.raises(ValueError, match="finite non-negative"):
        budget.with_reserved_tail(value)
