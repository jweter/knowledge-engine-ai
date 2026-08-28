from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.copilot.discovery_adapter import (
    DiscoveryAdapterBudget,
    DiscoveryAdapterContractError,
    execute_general_query_plan_discovery,
)
from knowledge_engine_ai.general_query_plan import (
    ConceptGroup,
    EvidenceScope,
    GeneralQueryPlan,
    SearchTrack,
    compile_general_query_plan,
)
from knowledge_engine_ai.ke_client import (
    FederatedCandidateSummary,
    FederatedDiscoveryResult,
    FederatedProviderStatus,
)


def _plan() -> GeneralQueryPlan:
    return compile_general_query_plan(
        "Do energy drinks affect blood pressure?",
        concepts=(
            ConceptGroup("exposure", "energy drink", ("Monster Energy",)),
            ConceptGroup("outcome", "blood pressure", ("hypertension",)),
        ),
        tracks=(
            SearchTrack(
                track_id="direct",
                purpose="Direct evidence.",
                scope=EvidenceScope.DIRECT,
                concept_ids=("exposure", "outcome"),
                max_variants=3,
            ),
            SearchTrack(
                track_id="counter",
                purpose="Null and contradictory evidence.",
                scope=EvidenceScope.COUNTEREVIDENCE,
                concept_ids=("exposure", "outcome"),
                fixed_terms=("no significant change",),
                max_variants=3,
            ),
        ),
        max_total_variants=4,
    )


def _result(query: str, number: int) -> FederatedDiscoveryResult:
    return FederatedDiscoveryResult(
        search_run_id=f"search-run-{number}",
        query_text=query,
        completeness="complete",
        provider_statuses=(
            FederatedProviderStatus(
                provider="pubmed",
                outcome="success",
                attempted=True,
                result_count=1,
                reason=None,
            ),
            FederatedProviderStatus(
                provider="openalex",
                outcome="success",
                attempted=True,
                result_count=1,
                reason=None,
            ),
        ),
        candidates=(
            FederatedCandidateSummary(
                canonical_id=f"candidate-{number}",
                title=f"Candidate {number}",
                doi=None,
                publication_year=2026,
                providers=("openalex", "pubmed"),
            ),
        ),
        provider_disagreements=None,
        search_run_created_at="2026-08-28T00:00:00Z",
    )


def test_adapter_executes_bounded_variants_and_preserves_provenance(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        calls.append({"query": query, **kwargs})
        return _result(query, len(calls))

    plan = _plan()
    result = execute_general_query_plan_discovery(
        plan,
        ledger_root=tmp_path,
        providers=("pubmed", "openalex"),
        budget=DiscoveryAdapterBudget(
            max_variant_calls=3,
            max_provider_attempts=6,
            per_variant_limit=12,
        ),
        project_id="project-1",
        research_question_id="rq-1",
        discover=fake_discover,
    )

    assert len(calls) == 3
    assert result.selected_variant_ids == tuple(
        variant.variant_id for variant in plan.query_variants[:3]
    )
    assert result.omitted_variant_ids == (plan.query_variants[3].variant_id,)
    assert {run.track_id for run in result.runs} == {"direct", "counter"}
    assert result.search_run_ids == ("search-run-1", "search-run-2", "search-run-3")
    assert result.all_variants_executed is False

    for call in calls:
        assert call["providers"] == ("pubmed", "openalex")
        assert call["limit"] == 12
        assert call["project_id"] == "project-1"
        assert call["research_question_id"] == "rq-1"

    assert result.runs[0].track_id == "direct"
    assert result.runs[0].scope is EvidenceScope.DIRECT
    assert result.runs[0].result.search_run_id == "search-run-1"
    assert result.runs[0].result.provider_statuses[0].provider == "pubmed"
    assert result.to_dict()["search_run_ids"] == [
        "search-run-1",
        "search-run-2",
        "search-run-3",
    ]


def test_adapter_refuses_budget_that_would_starve_a_search_track(tmp_path: Path) -> None:
    called = False

    def fake_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        nonlocal called
        called = True
        return _result(query, 1)

    with pytest.raises(ValueError, match="one variant call per search track"):
        execute_general_query_plan_discovery(
            _plan(),
            ledger_root=tmp_path,
            providers=("pubmed",),
            budget=DiscoveryAdapterBudget(max_variant_calls=1, max_provider_attempts=1),
            discover=fake_discover,
        )

    assert called is False


def test_adapter_refuses_provider_multiplication_above_budget(tmp_path: Path) -> None:
    called = False

    def fake_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        nonlocal called
        called = True
        return _result(query, 1)

    with pytest.raises(ValueError, match="provider attempts"):
        execute_general_query_plan_discovery(
            _plan(),
            ledger_root=tmp_path,
            providers=("pubmed", "openalex"),
            budget=DiscoveryAdapterBudget(max_variant_calls=3, max_provider_attempts=5),
            discover=fake_discover,
        )

    assert called is False


def test_adapter_requires_explicit_unique_providers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit non-empty provider set"):
        execute_general_query_plan_discovery(
            _plan(),
            ledger_root=tmp_path,
            providers=(),
            budget=DiscoveryAdapterBudget(max_variant_calls=2, max_provider_attempts=2),
        )

    with pytest.raises(ValueError, match="must be unique"):
        execute_general_query_plan_discovery(
            _plan(),
            ledger_root=tmp_path,
            providers=("pubmed", "pubmed"),
            budget=DiscoveryAdapterBudget(max_variant_calls=2, max_provider_attempts=4),
        )


def test_adapter_rejects_core_query_provenance_mismatch(tmp_path: Path) -> None:
    def fake_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        return _result("different query", 1)

    with pytest.raises(DiscoveryAdapterContractError, match="does not match"):
        execute_general_query_plan_discovery(
            _plan(),
            ledger_root=tmp_path,
            providers=("pubmed",),
            budget=DiscoveryAdapterBudget(max_variant_calls=2, max_provider_attempts=2),
            discover=fake_discover,
        )


def test_adapter_can_execute_every_compiled_variant(tmp_path: Path) -> None:
    calls = 0

    def fake_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        nonlocal calls
        calls += 1
        return _result(query, calls)

    plan = _plan()
    result = execute_general_query_plan_discovery(
        plan,
        ledger_root=tmp_path,
        providers=("pubmed",),
        budget=DiscoveryAdapterBudget(
            max_variant_calls=len(plan.query_variants),
            max_provider_attempts=len(plan.query_variants),
        ),
        discover=fake_discover,
    )

    assert calls == len(plan.query_variants)
    assert result.all_variants_executed is True
    assert result.omitted_variant_ids == ()
