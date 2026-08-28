"""Typed, bounded discovery-plan compiler (AI-FRD-3, opening slice).

`ke-ai discover` (`cli.py`) is a direct, person-invoked way to run one
federated discovery search through `ke_client.federated_discover()`. Its own
docstring is explicit that it does not decide *when* broader provider
coverage is warranted -- that judgment is deliberately left to AI-FRD-3's
"Discovery-plan compiler," so Research Copilot can eventually propose a
request without a person hand-typing `--providers`.

This module is that compiler's foundation: a `DiscoveryPlan` that only ever
names providers Core actually implements (a plan naming an unknown provider
fails to construct at all -- fail closed, never silently dropped or sent to
`ke` for Core to reject), makes its execution budget and per-provider depth
explicit, and an executor that runs the plan through the same
`ke_client.federated_discover()` subprocess boundary every other caller
uses, returning Core's own `search_run_id` so the run remains independently
replayable.

For a durable Research Session (`research_question_id` supplied), the executor
also repairs one measured failure mode from BT-0: a valid provider search can
return zero candidates when the full natural-language question is too literal.
In that case only, it tries a small deterministic sequence of progressively
broader keyword queries inside the *same* wall-clock budget. Ad-hoc/manual
discovery remains exactly one query. Provider outages/rate limits are not
"repaired" by rewording, and discovery candidates remain leads only -- they
still must pass acquisition, grounding, promotion, and re-retrieval before
becoming answer evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledge_engine_ai.copilot.discovery_broadening import (
    compile_zero_yield_broadening_queries,
)
from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded
from knowledge_engine_ai.ke_client import (
    FederatedDiscoveryResult,
    KeCommandError,
    federated_discover,
)

# Mirrors `_federated_discovery_registry`'s provider set in
# knowledge-engine-core's `entrypoint.py` -- PubMed, Crossref, OpenAlex,
# Semantic Scholar, and arXiv are the only providers `ke federated-discover`
# implements today. Keep in sync with Core's own registry; Core remains the
# source of truth and will itself reject a request this list gets wrong, but
# a plan should fail before ever shelling out, not after.
KNOWN_DISCOVERY_PROVIDERS: frozenset[str] = frozenset(
    {"pubmed", "crossref", "openalex", "semantic_scholar", "arxiv"}
)

# Matches Core's own `--limit` bound (`FederatedLimitOption`, min=1, max=100)
# so an out-of-range plan fails at compile time rather than at the `ke`
# subprocess boundary.
_MIN_LIMIT_PER_PROVIDER = 1
_MAX_LIMIT_PER_PROVIDER = 100

_MAX_EXECUTION_SECONDS_CEILING = 600.0
DEFAULT_RESEARCH_ZERO_YIELD_BROADENING_QUERIES = 2


class DiscoveryPlanError(ValueError):
    """A proposed discovery plan named an unknown provider or an invalid bound."""


@dataclass(frozen=True)
class DiscoveryPlan:
    """One typed, bounded, replayable request to run against Core's discovery capability.

    Validated eagerly in `__post_init__`: an unknown provider name or an
    out-of-range bound raises `DiscoveryPlanError` before any subprocess or
    network call, the "unknown tool/provider requests fail closed" exit
    criterion. `max_execution_seconds` is always explicit -- either the
    caller's own choice or `compile_discovery_plan`'s documented default --
    never an unbounded wait.
    """

    query: str
    providers: tuple[str, ...] | None
    limit_per_provider: int
    year_from: int | None
    year_to: int | None
    max_execution_seconds: float

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise DiscoveryPlanError("Discovery plan query must not be blank.")

        if self.providers is not None:
            if not self.providers:
                raise DiscoveryPlanError(
                    "Discovery plan providers must be omitted (None) or name at "
                    "least one provider -- an empty tuple is not a valid 'use every "
                    "provider' spelling."
                )
            unknown = sorted(set(self.providers) - KNOWN_DISCOVERY_PROVIDERS)
            if unknown:
                allowed = ", ".join(sorted(KNOWN_DISCOVERY_PROVIDERS))
                raise DiscoveryPlanError(
                    f"Discovery plan named unknown provider(s): {', '.join(unknown)}. "
                    f"Known providers: {allowed}."
                )

        if not _MIN_LIMIT_PER_PROVIDER <= self.limit_per_provider <= _MAX_LIMIT_PER_PROVIDER:
            raise DiscoveryPlanError(
                "Discovery plan limit_per_provider must be between "
                f"{_MIN_LIMIT_PER_PROVIDER} and {_MAX_LIMIT_PER_PROVIDER}."
            )

        if self.year_from is not None and not 1000 <= self.year_from <= 9999:
            raise DiscoveryPlanError("Discovery plan year_from must be a four-digit year.")
        if self.year_to is not None and not 1000 <= self.year_to <= 9999:
            raise DiscoveryPlanError("Discovery plan year_to must be a four-digit year.")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise DiscoveryPlanError("Discovery plan year_from must not be after year_to.")

        if not 0 < self.max_execution_seconds <= _MAX_EXECUTION_SECONDS_CEILING:
            raise DiscoveryPlanError(
                "Discovery plan max_execution_seconds must be a positive number no "
                f"greater than {_MAX_EXECUTION_SECONDS_CEILING:.0f}."
            )


def compile_discovery_plan(
    query: str,
    *,
    providers: tuple[str, ...] | None = None,
    limit_per_provider: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    max_execution_seconds: float = 60.0,
) -> DiscoveryPlan:
    """Validate and return one `DiscoveryPlan`, or raise `DiscoveryPlanError`.

    This is the single entry point a future planning caller (Research
    Copilot, or a person) should use to build a plan -- never construct
    `DiscoveryPlan` with unvalidated, caller-supplied provider names by
    hand-bypassing this function; `DiscoveryPlan.__post_init__` enforces the
    same checks either way, so there is no bypass, but this name is the
    documented "compiler" entry point the roadmap describes.
    """

    return DiscoveryPlan(
        query=query,
        providers=providers,
        limit_per_provider=limit_per_provider,
        year_from=year_from,
        year_to=year_to,
        max_execution_seconds=max_execution_seconds,
    )


def execute_discovery_plan(
    plan: DiscoveryPlan,
    *,
    ledger_root: Path,
    openalex_api_key: str | None = None,
    semantic_scholar_api_key: str | None = None,
    research_question_id: str | None = None,
    ke_executable: str = "ke",
) -> FederatedDiscoveryResult:
    """Run a compiled plan through Core and return the final valid discovery snapshot.

    One `ExecutionBudget` covers the initial request and every optional broadening
    request, so retries cannot silently widen the caller's wall-clock budget.

    `research_question_id` is call-time run-identity context. When omitted,
    behavior is the historical one-query execution path. When supplied, a valid
    zero-candidate result may trigger up to
    `DEFAULT_RESEARCH_ZERO_YIELD_BROADENING_QUERIES` deterministic broader
    searches. Broadening stops immediately when candidates appear or when no
    provider actually evaluated the current wording. Every Core call keeps the
    same `research_question_id`, so search-run provenance remains replayable.

    If a fallback attempt itself fails or exhausts the remaining budget, the
    executor returns the last *valid* zero-yield snapshot rather than converting a
    successfully executed discovery step into a hard failure. Failure of the
    initial request still propagates normally.
    """

    execution_budget = ExecutionBudget.from_timeout(plan.max_execution_seconds)
    result = _execute_query(
        plan.query,
        plan=plan,
        ledger_root=ledger_root,
        openalex_api_key=openalex_api_key,
        semantic_scholar_api_key=semantic_scholar_api_key,
        research_question_id=research_question_id,
        ke_executable=ke_executable,
        execution_budget=execution_budget,
    )

    if research_question_id is None or result.candidates or not _can_repair_with_broader_query(result):
        return result

    broadened_queries = compile_zero_yield_broadening_queries(
        plan.query,
        max_queries=DEFAULT_RESEARCH_ZERO_YIELD_BROADENING_QUERIES,
    )
    for query in broadened_queries:
        try:
            broadened_result = _execute_query(
                query,
                plan=plan,
                ledger_root=ledger_root,
                openalex_api_key=openalex_api_key,
                semantic_scholar_api_key=semantic_scholar_api_key,
                research_question_id=research_question_id,
                ke_executable=ke_executable,
                execution_budget=execution_budget,
            )
        except (KeCommandError, ExecutionBudgetExceeded):
            return result
        result = broadened_result
        if result.candidates or not _can_repair_with_broader_query(result):
            break
    return result


def _execute_query(
    query: str,
    *,
    plan: DiscoveryPlan,
    ledger_root: Path,
    openalex_api_key: str | None,
    semantic_scholar_api_key: str | None,
    research_question_id: str | None,
    ke_executable: str,
    execution_budget: ExecutionBudget,
) -> FederatedDiscoveryResult:
    return federated_discover(
        query,
        ledger_root=ledger_root,
        limit=plan.limit_per_provider,
        providers=plan.providers,
        openalex_api_key=openalex_api_key,
        semantic_scholar_api_key=semantic_scholar_api_key,
        research_question_id=research_question_id,
        ke_executable=ke_executable,
        execution_budget=execution_budget,
    )


def _can_repair_with_broader_query(result: FederatedDiscoveryResult) -> bool:
    """Whether wording, rather than provider availability, can explain zero yield."""

    return any(
        status.attempted and status.outcome in {"empty", "success"}
        for status in result.provider_statuses
    )


__all__ = [
    "DEFAULT_RESEARCH_ZERO_YIELD_BROADENING_QUERIES",
    "KNOWN_DISCOVERY_PROVIDERS",
    "DiscoveryPlan",
    "DiscoveryPlanError",
    "compile_discovery_plan",
    "execute_discovery_plan",
]
