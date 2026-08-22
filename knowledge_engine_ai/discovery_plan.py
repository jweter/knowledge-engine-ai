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
replayable (`ke federated-discover-report`... conceptually -- Core does not
have a report command for this yet, the ledger itself is the replay record).

Deciding *when* a Research Session should invoke this compiler (rather than
running locally against the already-imported corpus) is future work, not
this slice -- see `docs/roadmap/federated_discovery_orchestration_adoption.md`'s
AI-FRD-3 exit criteria and this module's own limitations noted there.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.ke_client import FederatedDiscoveryResult, federated_discover

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
    """Run a compiled plan through Core's `ke federated-discover` and return its result.

    Always builds an `ExecutionBudget` from `plan.max_execution_seconds` --
    the plan's own explicit bound, not the caller's ambient timeout
    preference -- so a compiled plan's execution budget cannot be silently
    widened by whoever happens to execute it. The returned
    `FederatedDiscoveryResult.search_run_id` is Core's own persisted ledger
    ID: Core's `FederatedSearchLedger`, not this function, is the durable,
    replayable record of what actually ran.

    `research_question_id` is call-time run-identity context, not a plan
    parameter -- deliberately not on `DiscoveryPlan` itself (the same
    category as `ledger_root` and the provider API keys, per
    `docs/roadmap/answer_session_versioning_design.md`). Forwarded verbatim
    to `federated_discover`/Core's `--research-question-id` flag so a later
    caller can find this run via `federated_discover_history`; omitting it
    preserves every existing caller's behavior exactly.
    """

    return federated_discover(
        plan.query,
        ledger_root=ledger_root,
        limit=plan.limit_per_provider,
        providers=plan.providers,
        openalex_api_key=openalex_api_key,
        semantic_scholar_api_key=semantic_scholar_api_key,
        research_question_id=research_question_id,
        ke_executable=ke_executable,
        execution_budget=ExecutionBudget.from_timeout(plan.max_execution_seconds),
    )


__all__ = [
    "KNOWN_DISCOVERY_PROVIDERS",
    "DiscoveryPlan",
    "DiscoveryPlanError",
    "compile_discovery_plan",
    "execute_discovery_plan",
]
