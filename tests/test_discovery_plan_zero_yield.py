from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_engine_ai.discovery_plan as discovery_plan
from knowledge_engine_ai.ke_client import (
    FederatedCandidateSummary,
    FederatedDiscoveryResult,
    FederatedProviderStatus,
    KeCommandError,
)

QUESTION = (
    "In healthy adults, does listening to music during exercise improve endurance "
    "performance compared with exercising without music?"
)


def _result(
    query: str,
    *,
    outcome: str = "empty",
    candidates: tuple[FederatedCandidateSummary, ...] = (),
    run_id: str = "run-1",
) -> FederatedDiscoveryResult:
    return FederatedDiscoveryResult(
        search_run_id=run_id,
        query_text=query,
        completeness="complete",
        provider_statuses=(
            FederatedProviderStatus(
                provider="pubmed",
                outcome=outcome,
                attempted=True,
                result_count=len(candidates),
                reason=None,
            ),
        ),
        candidates=candidates,
        provider_disagreements=None,
        search_run_created_at="2026-08-28T00:00:00Z",
    )


def _candidate() -> FederatedCandidateSummary:
    return FederatedCandidateSummary(
        canonical_id="doi:10.1016/j.psychsport.2026.103116",
        title="Feel the beat, not the burn",
        doi="10.1016/j.psychsport.2026.103116",
        publication_year=2026,
        providers=("pubmed",),
    )


def test_research_session_broadens_zero_yield_until_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str | None, int]] = []

    def fake_federated_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        raw_research_question_id = kwargs.get("research_question_id")
        research_question_id = (
            raw_research_question_id if isinstance(raw_research_question_id, str) else None
        )
        calls.append((query, research_question_id, id(kwargs["execution_budget"])))
        if query == QUESTION:
            return _result(query)
        if query == "music exercise endurance":
            return _result(query, outcome="success", candidates=(_candidate(),), run_id="run-2")
        raise AssertionError(f"Unexpected discovery query: {query}")

    monkeypatch.setattr(discovery_plan, "federated_discover", fake_federated_discover)
    plan = discovery_plan.compile_discovery_plan(
        QUESTION,
        providers=("pubmed",),
        limit_per_provider=10,
        max_execution_seconds=45.0,
    )

    result = discovery_plan.execute_discovery_plan(
        plan,
        ledger_root=tmp_path,
        research_question_id="rq-music-endurance",
    )

    assert result.search_run_id == "run-2"
    assert result.query_text == "music exercise endurance"
    assert len(result.candidates) == 1
    assert [call[0] for call in calls] == [QUESTION, "music exercise endurance"]
    assert all(call[1] == "rq-music-endurance" for call in calls)
    assert len({call[2] for call in calls}) == 1  # one shared wall-clock budget


def test_manual_discovery_preserves_single_query_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_federated_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        calls.append(query)
        return _result(query)

    monkeypatch.setattr(discovery_plan, "federated_discover", fake_federated_discover)
    plan = discovery_plan.compile_discovery_plan(QUESTION, providers=("pubmed",))

    result = discovery_plan.execute_discovery_plan(plan, ledger_root=tmp_path)

    assert result.query_text == QUESTION
    assert calls == [QUESTION]


def test_rate_limited_provider_does_not_trigger_query_rewrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_federated_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        calls.append(query)
        return _result(query, outcome="rate_limited")

    monkeypatch.setattr(discovery_plan, "federated_discover", fake_federated_discover)
    plan = discovery_plan.compile_discovery_plan(QUESTION, providers=("pubmed",))

    result = discovery_plan.execute_discovery_plan(
        plan,
        ledger_root=tmp_path,
        research_question_id="rq-rate-limited",
    )

    assert result.query_text == QUESTION
    assert calls == [QUESTION]


def test_failed_fallback_keeps_last_valid_zero_yield_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_federated_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        calls.append(query)
        if len(calls) == 1:
            return _result(query)
        raise KeCommandError("provider transport failed during fallback")

    monkeypatch.setattr(discovery_plan, "federated_discover", fake_federated_discover)
    plan = discovery_plan.compile_discovery_plan(QUESTION, providers=("pubmed",))

    result = discovery_plan.execute_discovery_plan(
        plan,
        ledger_root=tmp_path,
        research_question_id="rq-fallback-failure",
    )

    assert result.query_text == QUESTION
    assert result.candidates == ()
    assert calls == [QUESTION, "music exercise endurance"]
