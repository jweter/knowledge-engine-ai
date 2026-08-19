from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_engine_ai.discovery_plan as discovery_plan
from knowledge_engine_ai.discovery_plan import (
    KNOWN_DISCOVERY_PROVIDERS,
    DiscoveryPlan,
    DiscoveryPlanError,
    compile_discovery_plan,
    execute_discovery_plan,
)
from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.ke_client import FederatedDiscoveryResult


def test_compile_discovery_plan_accepts_a_minimal_valid_request() -> None:
    plan = compile_discovery_plan("semaglutide weight loss")

    assert plan.query == "semaglutide weight loss"
    assert plan.providers is None
    assert plan.limit_per_provider == 20
    assert plan.max_execution_seconds == 60.0


def test_compile_discovery_plan_accepts_every_known_provider() -> None:
    plan = compile_discovery_plan(
        "glp-1 receptor agonist",
        providers=tuple(sorted(KNOWN_DISCOVERY_PROVIDERS)),
    )

    assert set(plan.providers or ()) == KNOWN_DISCOVERY_PROVIDERS


def test_discovery_plan_rejects_an_unknown_provider() -> None:
    with pytest.raises(DiscoveryPlanError, match="unknown provider"):
        compile_discovery_plan("query", providers=("pubmed", "unpaywall"))


def test_discovery_plan_rejects_an_empty_provider_tuple() -> None:
    with pytest.raises(DiscoveryPlanError, match="at least one provider"):
        compile_discovery_plan("query", providers=())


def test_discovery_plan_rejects_a_blank_query() -> None:
    with pytest.raises(DiscoveryPlanError, match="must not be blank"):
        compile_discovery_plan("   ")


@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_discovery_plan_rejects_an_out_of_range_limit(limit: int) -> None:
    with pytest.raises(DiscoveryPlanError, match="limit_per_provider"):
        compile_discovery_plan("query", limit_per_provider=limit)


@pytest.mark.parametrize("limit", [1, 20, 100])
def test_discovery_plan_accepts_the_boundary_limits(limit: int) -> None:
    plan = compile_discovery_plan("query", limit_per_provider=limit)
    assert plan.limit_per_provider == limit


def test_discovery_plan_rejects_year_from_after_year_to() -> None:
    with pytest.raises(DiscoveryPlanError, match="year_from must not be after year_to"):
        compile_discovery_plan("query", year_from=2026, year_to=2020)


@pytest.mark.parametrize("year", [999, 10000, 0])
def test_discovery_plan_rejects_a_non_four_digit_year(year: int) -> None:
    with pytest.raises(DiscoveryPlanError, match="four-digit year"):
        compile_discovery_plan("query", year_from=year)


@pytest.mark.parametrize("seconds", [0, -5, 600.01, float("inf"), float("nan")])
def test_discovery_plan_rejects_an_invalid_execution_budget(seconds: float) -> None:
    with pytest.raises(DiscoveryPlanError, match="max_execution_seconds"):
        compile_discovery_plan("query", max_execution_seconds=seconds)


def test_discovery_plan_accepts_the_execution_budget_ceiling() -> None:
    plan = compile_discovery_plan("query", max_execution_seconds=600.0)
    assert plan.max_execution_seconds == 600.0


def test_discovery_plan_is_frozen_and_hand_construction_still_validates() -> None:
    # DiscoveryPlan.__post_init__ enforces the same checks even if a caller
    # bypasses compile_discovery_plan and constructs the dataclass directly --
    # there is no way to hold an invalid DiscoveryPlan instance.
    with pytest.raises(DiscoveryPlanError, match="unknown provider"):
        DiscoveryPlan(
            query="q",
            providers=("not_a_real_provider",),
            limit_per_provider=20,
            year_from=None,
            year_to=None,
            max_execution_seconds=60.0,
        )


def test_execute_discovery_plan_forwards_fields_and_builds_an_explicit_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_federated_discover(
        query: str,
        *,
        ledger_root: Path,
        limit: int,
        providers: tuple[str, ...] | None,
        openalex_api_key: str | None,
        semantic_scholar_api_key: str | None,
        ke_executable: str,
        execution_budget: ExecutionBudget | None,
    ) -> FederatedDiscoveryResult:
        captured["query"] = query
        captured["ledger_root"] = ledger_root
        captured["limit"] = limit
        captured["providers"] = providers
        captured["ke_executable"] = ke_executable
        captured["execution_budget"] = execution_budget
        return FederatedDiscoveryResult(
            search_run_id="run-xyz",
            query_text=query,
            completeness="complete",
            provider_statuses=(),
            candidates=(),
            provider_disagreements=None,
            search_run_created_at=None,
        )

    monkeypatch.setattr(discovery_plan, "federated_discover", fake_federated_discover)

    plan = compile_discovery_plan(
        "semaglutide weight loss",
        providers=("pubmed", "openalex"),
        limit_per_provider=15,
        max_execution_seconds=30.0,
    )
    ledger_root = tmp_path / "ledger"

    result = execute_discovery_plan(
        plan,
        ledger_root=ledger_root,
        openalex_api_key="key-1",
    )

    assert result.search_run_id == "run-xyz"
    assert captured["query"] == "semaglutide weight loss"
    assert captured["ledger_root"] == ledger_root
    assert captured["limit"] == 15
    assert captured["providers"] == ("pubmed", "openalex")
    assert captured["ke_executable"] == "ke"
    budget = captured["execution_budget"]
    assert isinstance(budget, ExecutionBudget)
    # The budget was built from the plan's own bound, not left unbounded.
    assert budget.remaining_seconds() <= 30.0
