"""Bounded adapter from GQR-2 query plans to Core federated discovery.

This module is the provider-execution boundary for General Question Research Loop
v1.  It consumes an already validated :class:`GeneralQueryPlan`, selects a
bounded set of query variants without starving any search track, executes those
variants through Core's public ``ke federated-discover`` boundary, and retains
variant/track/scope/provider/search-run provenance for every call.

Search results remain discovery candidates only.  Nothing in this adapter
promotes a candidate to an Evidence Record or makes a factual claim citable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.general_query_plan import (
    MAX_TOTAL_VARIANTS,
    EvidenceScope,
    GeneralQueryPlan,
    QueryVariant,
)
from knowledge_engine_ai.ke_client import FederatedDiscoveryResult, federated_discover

MAX_DISCOVERY_PROVIDERS = 8
MAX_CANDIDATES_PER_VARIANT = 100
MAX_PROVIDER_ATTEMPTS = MAX_TOTAL_VARIANTS * MAX_DISCOVERY_PROVIDERS

DiscoveryCallable = Callable[..., FederatedDiscoveryResult]


class DiscoveryAdapterContractError(RuntimeError):
    """Core returned a discovery result that cannot be tied to the executed query."""


@dataclass(frozen=True)
class DiscoveryAdapterBudget:
    """Explicit hard bounds for one query-plan discovery execution.

    ``max_variant_calls`` bounds Core command invocations.  ``max_provider_attempts``
    additionally bounds the multiplication of selected variants by requested
    providers.  ``per_variant_limit`` bounds candidate volume returned per Core
    call.  The adapter refuses to execute if the budget cannot cover at least one
    variant for every search track.
    """

    max_variant_calls: int
    max_provider_attempts: int
    per_variant_limit: int = 20

    def __post_init__(self) -> None:
        if not 1 <= self.max_variant_calls <= MAX_TOTAL_VARIANTS:
            raise ValueError(
                f"max_variant_calls must be between 1 and {MAX_TOTAL_VARIANTS}."
            )
        if not 1 <= self.max_provider_attempts <= MAX_PROVIDER_ATTEMPTS:
            raise ValueError(
                f"max_provider_attempts must be between 1 and {MAX_PROVIDER_ATTEMPTS}."
            )
        if not 1 <= self.per_variant_limit <= MAX_CANDIDATES_PER_VARIANT:
            raise ValueError(
                "per_variant_limit must be between 1 and "
                f"{MAX_CANDIDATES_PER_VARIANT}."
            )


@dataclass(frozen=True)
class QueryVariantDiscoveryRun:
    """One executed query variant plus the full typed Core discovery result."""

    variant_id: str
    track_id: str
    scope: EvidenceScope
    query: str
    result: FederatedDiscoveryResult

    def to_dict(self) -> dict[str, object]:
        """Return an inspectable provenance-preserving representation."""

        return {
            "variant_id": self.variant_id,
            "track_id": self.track_id,
            "scope": self.scope.value,
            "query": self.query,
            "search_run_id": self.result.search_run_id,
            "search_run_created_at": self.result.search_run_created_at,
            "completeness": self.result.completeness,
            "provider_outcomes": [
                {
                    "provider": status.provider,
                    "outcome": status.outcome,
                    "attempted": status.attempted,
                    "result_count": status.result_count,
                    "reason": status.reason,
                }
                for status in self.result.provider_statuses
            ],
            "candidates": [
                {
                    "canonical_id": candidate.canonical_id,
                    "title": candidate.title,
                    "doi": candidate.doi,
                    "publication_year": candidate.publication_year,
                    "providers": list(candidate.providers),
                }
                for candidate in self.result.candidates
            ],
        }


@dataclass(frozen=True)
class QueryPlanDiscoveryResult:
    """Bounded execution record for one GeneralQueryPlan."""

    plan_schema_version: int
    question: str
    providers: tuple[str, ...]
    selected_variant_ids: tuple[str, ...]
    omitted_variant_ids: tuple[str, ...]
    runs: tuple[QueryVariantDiscoveryRun, ...]

    @property
    def all_variants_executed(self) -> bool:
        """Whether the explicit budget covered every compiled variant."""

        return not self.omitted_variant_ids

    @property
    def search_run_ids(self) -> tuple[str, ...]:
        """Core-owned search-run IDs in execution order."""

        return tuple(run.result.search_run_id for run in self.runs)

    def to_dict(self) -> dict[str, object]:
        """Return an inspectable execution snapshot without reinterpreting evidence."""

        return {
            "plan_schema_version": self.plan_schema_version,
            "question": self.question,
            "providers": list(self.providers),
            "selected_variant_ids": list(self.selected_variant_ids),
            "omitted_variant_ids": list(self.omitted_variant_ids),
            "all_variants_executed": self.all_variants_executed,
            "search_run_ids": list(self.search_run_ids),
            "runs": [run.to_dict() for run in self.runs],
        }


def execute_general_query_plan_discovery(
    plan: GeneralQueryPlan,
    *,
    ledger_root: Path,
    providers: tuple[str, ...],
    budget: DiscoveryAdapterBudget,
    project_id: str | None = None,
    research_question_id: str | None = None,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
    discover: DiscoveryCallable = federated_discover,
) -> QueryPlanDiscoveryResult:
    """Execute a bounded subset of a validated query plan through Core.

    The caller must provide both the provider set and a hard execution budget.
    The adapter selects one canonical/first available variant per search track
    before allocating any remaining variant-call budget in original plan order.
    This prevents synonym-rich tracks from consuming execution capacity while
    still allowing a caller to intentionally cap a large plan below its total
    compiled variant count.

    ``execution_budget`` is the existing shared wall-clock deadline used by the
    Research Copilot.  It is forwarded to every Core call, so the operation is
    bounded both by deterministic call/provider counts and by elapsed time.
    """

    _validate_providers(providers)
    _validate_optional_id("project_id", project_id)
    _validate_optional_id("research_question_id", research_question_id)

    if budget.max_variant_calls < len(plan.tracks):
        raise ValueError(
            "Discovery budget must allow at least one variant call per search track."
        )

    selected = _select_variants(plan, budget.max_variant_calls)
    provider_attempt_count = len(selected) * len(providers)
    if provider_attempt_count > budget.max_provider_attempts:
        raise ValueError(
            "Discovery budget would be exceeded before execution: "
            f"{len(selected)} variants x {len(providers)} providers = "
            f"{provider_attempt_count} provider attempts, above the configured "
            f"maximum of {budget.max_provider_attempts}."
        )

    selected_ids = tuple(variant.variant_id for variant in selected)
    selected_id_set = set(selected_ids)
    omitted_ids = tuple(
        variant.variant_id
        for variant in plan.query_variants
        if variant.variant_id not in selected_id_set
    )

    runs: list[QueryVariantDiscoveryRun] = []
    for variant in selected:
        result = discover(
            variant.query,
            ledger_root=ledger_root,
            limit=budget.per_variant_limit,
            providers=providers,
            project_id=project_id,
            research_question_id=research_question_id,
            ke_executable=ke_executable,
            execution_budget=execution_budget,
        )
        if result.query_text != variant.query:
            raise DiscoveryAdapterContractError(
                "Core discovery result query does not match the executed query variant "
                f"{variant.variant_id!r}."
            )
        runs.append(
            QueryVariantDiscoveryRun(
                variant_id=variant.variant_id,
                track_id=variant.track_id,
                scope=variant.scope,
                query=variant.query,
                result=result,
            )
        )

    return QueryPlanDiscoveryResult(
        plan_schema_version=plan.schema_version,
        question=plan.question,
        providers=providers,
        selected_variant_ids=selected_ids,
        omitted_variant_ids=omitted_ids,
        runs=tuple(runs),
    )


def _select_variants(plan: GeneralQueryPlan, max_variant_calls: int) -> tuple[QueryVariant, ...]:
    selected: list[QueryVariant] = []
    selected_ids: set[str] = set()

    for track in plan.tracks:
        variant = next(
            candidate
            for candidate in plan.query_variants
            if candidate.track_id == track.track_id
        )
        selected.append(variant)
        selected_ids.add(variant.variant_id)

    for variant in plan.query_variants:
        if len(selected) >= max_variant_calls:
            break
        if variant.variant_id in selected_ids:
            continue
        selected.append(variant)
        selected_ids.add(variant.variant_id)

    return tuple(selected)


def _validate_providers(providers: tuple[str, ...]) -> None:
    if not providers:
        raise ValueError("Discovery adapter requires an explicit non-empty provider set.")
    if len(providers) > MAX_DISCOVERY_PROVIDERS:
        raise ValueError(
            f"Discovery adapter supports at most {MAX_DISCOVERY_PROVIDERS} providers per run."
        )
    if len(providers) != len(set(providers)):
        raise ValueError("Discovery providers must be unique.")
    if any(not provider.strip() for provider in providers):
        raise ValueError("Discovery provider names must be non-blank.")


def _validate_optional_id(name: str, value: str | None) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{name} must be non-blank when supplied.")


__all__ = [
    "DiscoveryAdapterBudget",
    "DiscoveryAdapterContractError",
    "QueryPlanDiscoveryResult",
    "QueryVariantDiscoveryRun",
    "execute_general_query_plan_discovery",
]
