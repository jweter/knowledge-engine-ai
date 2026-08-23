"""AI-FRD-3/AI-FRD-4 wiring: the coverage-gap policy that decides *when* a
Research Session invokes bounded federated discovery / citation-snowball.

`docs/roadmap/federated_discovery_orchestration_adoption.md`'s objective:
"Let Research Copilot plan bounded federated-discovery requests to Core
rather than calling provider APIs directly, without ever treating provider
count as evidence quality." AI-FRD-3 (`discovery_plan.py`'s compiler) and
AI-FRD-4 (`ke_client.citation_snowball()`) both already exist, tested and
live-verified, but neither had a caller inside `run_research_question`'s own
planning -- deciding *when* to invoke either one was explicitly left open,
flagged in that roadmap doc as needing product-owner judgment. Jeremy's
decision (recorded in the PR that introduced this module): "continue with
the FRD and widen the search." This module is that continuation.

Two independent, deterministic trigger rules -- never an LLM judgment call,
matching AI-O3/AI-O5's own "no model dynamically deciding execution"
discipline already established elsewhere in this orchestrator:

1. **Federated discovery** fires when the fixed workflow's own corpus
   retrieval (primary branch) succeeded but the deduplicated evidence-record
   coverage across the primary and contradiction-oriented branches together
   falls below ``policy.min_evidence_record_coverage`` -- "insufficient
   initial evidence coverage," the roadmap doc's own example trigger. It
   does *not* fire when the primary retrieval branch itself failed (a Core
   problem the workflow-integrity ISA criterion already blocks the session
   on; broadening the provider search would not fix a broken local
   retrieval call and would just add cost/latency to a run already
   failing).

2. **Citation-snowball** fires under the same coverage-gap signal, using a
   deterministic seed-selection policy: the DOIs of the primary retrieval
   branch's own ranked papers (already-known, already-relevant works in the
   local corpus), in rank order, deduplicated, capped at
   ``policy.citation_snowball_seed_limit``. This is the roadmap's own
   "seed known landmark work -> inspect references -> inspect citing works"
   pattern, grounded in the corpus we already trust rather than an
   unvetted discovery candidate. When the corpus has no DOI-bearing paper
   to seed from, the snowball step is skipped and the reason is recorded --
   it never blocks or fails the run.

Every discovery/snowball outcome is recorded as its own durable
`ResearchEvent` (mirrors `workflow.py`'s "one step's failure does not stop
the remaining fixed steps, and every step is recorded" discipline) and
returned on `DiscoveryAugmentationResult` for `run_research_question` to
surface end-to-end. Candidates are **never** written into `source_ids` --
that field is `SessionTrace`'s "what evidence supported the output" answer,
and a federated-discovery/citation-snowball candidate is not an Evidence
Record (it was not acquired, screened, or reviewed) -- exactly the
distinction `ke-ai discover`/`ke-ai citation-snowball`'s own text output
already prints ("Discovery only -- these are not Evidence Records and were
not acquired."). Nothing here feeds a candidate to `synthesize_answer`
either; the narrative still cites only grounded `EvidenceRecord`s. Provider
*count* is deliberately not read anywhere in this module as a quality or
confidence signal -- only ``completeness``/``provider_statuses`` (Core's own
recorded facts) and candidate counts (a coverage/leads metric, not a truth
metric) are surfaced.

This whole policy is opt-in: `run_research_question` only evaluates it when
a caller supplies a `FederatedDiscoveryPolicy` (default `None`). This
follows `docs/agent-development-policy.md` section 2's cost-consciousness
rule -- a new capability with real external-provider cost/latency must stay
off an existing default path, reachable only through explicit opt-in.
Jeremy's "widen the search" decision authorizes building and wiring the
capability; it does not by itself make every existing caller (e.g. Web's
`/ask`) pay for it without that caller choosing to pass a policy.

Issue #69 Stage 4 (candidate triage and acquisition), first orchestration
slice: when a triggered federated-discovery run returns its own candidates,
and `policy.enable_acquisition_plan` is turned on, this module additionally
requests a bounded Core acquisition plan
(`ke_client.general_question_acquisition_plan`, PR #72's wrapper around
Core's `ke general-question-acquisition-plan` -- CORE-GQR-1/GQR-2) for that
run's candidate IDs. This decides *when* to request a plan and *which*
candidates to request it for -- the two gaps
`docs/roadmap/general_question_research_loop_v1.md`'s GQR-3 section named
as this repository's own next continuation -- but it is still only a
resolved *plan*: Core's own CORE-GQR-3 (acquisition routing through PMC/
Europe PMC/Unpaywall/CORE) and CORE-GQR-4 (persist and parse) remain not
started, so no `eligible_full_text` disposition here implies a source was
actually downloaded, ingested, or promoted to an Evidence Record. Nothing
in this plan is ever fed to `synthesize_answer` -- exactly the same
discovery-is-not-evidence discipline the rest of this module already
applies to federated-discovery/citation-snowball candidates.

`enable_acquisition_plan` defaults to `False`, unlike
`enable_federated_discovery`/`enable_citation_snowball` (both `True`,
following Jeremy's "widen the search" decision for the FRD track above):
this is a distinct, newer capability along the separate GQR track that no
caller has yet opted a real session into, so every existing
`FederatedDiscoveryPolicy` caller -- including ones that already rely on
today's federated-discovery/citation-snowball defaults -- keeps paying for
exactly what it already paid for until it explicitly turns this on too.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine_ai.discovery_plan import (
    DiscoveryPlanError,
    compile_discovery_plan,
    execute_discovery_plan,
)
from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded
from knowledge_engine_ai.ke_client import (
    CitationSnowballResult,
    FederatedDiscoveryResult,
    GeneralQuestionAcquisitionPlanResult,
    KeCommandError,
    citation_snowball,
    general_question_acquisition_plan,
)
from knowledge_engine_ai.orchestrator.parallel_retrieval import ParallelRetrievalResult
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import ResearchEvent
from knowledge_engine_ai.sessions.repository import SessionRepository

_FEDERATED_DISCOVERY_NODE = "federated_discovery"
_CITATION_SNOWBALL_NODE = "citation_snowball"
_ACQUISITION_PLAN_NODE = "acquisition_plan"
_EXECUTOR_TYPE = "deterministic_tool"

# Conservative, clearly-labeled defaults -- Jeremy's "widen the search"
# decision authorized building and wiring this capability, but did not
# specify exact numeric budgets. These are this PR's own conservative
# choice, intentionally tighter than the person-invoked `ke-ai discover`/
# `ke-ai citation-snowball` CLI defaults (20/25/100/60s), since this path
# runs *autonomously*, without a person reviewing the request first.
# Override via `FederatedDiscoveryPolicy`'s fields; see the PR description
# for the reasoning trail.
DEFAULT_MIN_EVIDENCE_RECORD_COVERAGE = 3
DEFAULT_DISCOVERY_LIMIT_PER_PROVIDER = 10
DEFAULT_DISCOVERY_MAX_EXECUTION_SECONDS = 45.0
DEFAULT_SNOWBALL_SEED_LIMIT = 3
DEFAULT_SNOWBALL_MAX_DEPTH = 1
DEFAULT_SNOWBALL_LIMIT_PER_TRAVERSAL = 25
DEFAULT_SNOWBALL_MAX_CANDIDATES = 50
DEFAULT_SNOWBALL_MAX_EXECUTION_SECONDS = 30.0

# Issue #69 Stage 4: deliberately at or below Core's own command defaults
# (`max_candidates=10`, `max_full_text_acquisitions=5`,
# `max_elapsed_seconds=120` -- `GeneralQuestionAcquisitionRequest`'s own
# field defaults) since this path is autonomous, same reasoning as the
# discovery/snowball defaults above. This is still only a *plan* request
# (no download happens from this call), but it is a new, not-yet-widely-
# exercised capability, so its own budget stays conservative.
DEFAULT_ACQUISITION_PLAN_MAX_CANDIDATES = 10
DEFAULT_ACQUISITION_PLAN_MAX_FULL_TEXT_ACQUISITIONS = 3
DEFAULT_ACQUISITION_PLAN_MAX_ELAPSED_SECONDS = 60
DEFAULT_ACQUISITION_PLAN_ALLOW_METADATA_ONLY = True

# A tighter ceiling than `discovery_plan.py`'s own 600s -- this module's
# calls are autonomous (no person reviewing the request before it runs),
# so its own per-call budget ceiling is deliberately smaller.
_MAX_SUB_BUDGET_SECONDS_CEILING = 120.0


class DiscoveryPolicyError(ValueError):
    """A `FederatedDiscoveryPolicy` was constructed with an invalid bound."""


@dataclass(frozen=True)
class FederatedDiscoveryPolicy:
    """Bounded, explicit configuration for autonomous federated-discovery/citation-snowball.

    Passing an instance to `run_research_question` opts a caller into this
    milestone's wiring; leaving it `None` (the default) preserves the
    existing corpus-only behavior byte for byte. Validated eagerly in
    `__post_init__`, the same fail-closed-before-any-subprocess-call
    discipline `DiscoveryPlan` already uses -- an out-of-range bound raises
    `DiscoveryPolicyError` at policy construction, never at call time.
    """

    ledger_root: Path
    enable_federated_discovery: bool = True
    enable_citation_snowball: bool = True
    min_evidence_record_coverage: int = DEFAULT_MIN_EVIDENCE_RECORD_COVERAGE
    discovery_providers: tuple[str, ...] | None = None
    discovery_limit_per_provider: int = DEFAULT_DISCOVERY_LIMIT_PER_PROVIDER
    discovery_max_execution_seconds: float = DEFAULT_DISCOVERY_MAX_EXECUTION_SECONDS
    citation_snowball_seed_limit: int = DEFAULT_SNOWBALL_SEED_LIMIT
    citation_snowball_provider: str = "semantic_scholar"
    citation_snowball_directions: tuple[str, ...] = ("references", "citations")
    citation_snowball_max_depth: int = DEFAULT_SNOWBALL_MAX_DEPTH
    citation_snowball_limit_per_traversal: int = DEFAULT_SNOWBALL_LIMIT_PER_TRAVERSAL
    citation_snowball_max_candidates: int = DEFAULT_SNOWBALL_MAX_CANDIDATES
    citation_snowball_max_execution_seconds: float = DEFAULT_SNOWBALL_MAX_EXECUTION_SECONDS
    # Issue #69 Stage 4 (candidate triage and acquisition): off by default --
    # see this module's own docstring for why this one toggle does not
    # follow `enable_federated_discovery`/`enable_citation_snowball`'s
    # `True` default.
    enable_acquisition_plan: bool = False
    acquisition_plan_max_candidates: int = DEFAULT_ACQUISITION_PLAN_MAX_CANDIDATES
    acquisition_plan_max_full_text_acquisitions: int = (
        DEFAULT_ACQUISITION_PLAN_MAX_FULL_TEXT_ACQUISITIONS
    )
    acquisition_plan_max_elapsed_seconds: int = DEFAULT_ACQUISITION_PLAN_MAX_ELAPSED_SECONDS
    acquisition_plan_allow_metadata_only: bool = DEFAULT_ACQUISITION_PLAN_ALLOW_METADATA_ONLY
    openalex_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    ke_executable: str = "ke"

    def __post_init__(self) -> None:
        if self.min_evidence_record_coverage < 0:
            raise DiscoveryPolicyError("min_evidence_record_coverage must not be negative.")
        if self.citation_snowball_seed_limit < 0:
            raise DiscoveryPolicyError("citation_snowball_seed_limit must not be negative.")
        if not 1 <= self.discovery_limit_per_provider <= 100:
            raise DiscoveryPolicyError("discovery_limit_per_provider must be between 1 and 100.")
        if not 1 <= self.citation_snowball_max_depth <= 3:
            raise DiscoveryPolicyError("citation_snowball_max_depth must be between 1 and 3.")
        if self.citation_snowball_limit_per_traversal < 1:
            raise DiscoveryPolicyError("citation_snowball_limit_per_traversal must be at least 1.")
        if self.citation_snowball_max_candidates < 1:
            raise DiscoveryPolicyError("citation_snowball_max_candidates must be at least 1.")
        if not 1 <= self.acquisition_plan_max_candidates <= 100:
            raise DiscoveryPolicyError("acquisition_plan_max_candidates must be between 1 and 100.")
        if (
            not 0
            <= self.acquisition_plan_max_full_text_acquisitions
            <= (self.acquisition_plan_max_candidates)
        ):
            raise DiscoveryPolicyError(
                "acquisition_plan_max_full_text_acquisitions must be between 0 and "
                "acquisition_plan_max_candidates."
            )
        if not 1 <= self.acquisition_plan_max_elapsed_seconds <= _MAX_SUB_BUDGET_SECONDS_CEILING:
            raise DiscoveryPolicyError(
                "acquisition_plan_max_elapsed_seconds must be a positive integer no greater "
                f"than {_MAX_SUB_BUDGET_SECONDS_CEILING:.0f}."
            )
        for name in ("discovery_max_execution_seconds", "citation_snowball_max_execution_seconds"):
            value = getattr(self, name)
            if not 0 < value <= _MAX_SUB_BUDGET_SECONDS_CEILING:
                raise DiscoveryPolicyError(
                    f"{name} must be a positive number no greater than "
                    f"{_MAX_SUB_BUDGET_SECONDS_CEILING:.0f}."
                )


@dataclass(frozen=True)
class DiscoveryAugmentationResult:
    """What (if anything) the coverage-gap policy did this run, and why.

    `federated_discovery`/`citation_snowball` are Core-recorded discovery
    leads only -- never Evidence Records, never fed to `synthesize_answer`.
    `evidence_record_coverage` is the deduplicated evidence-record count
    the trigger decision was made from, kept here so the decision is
    independently auditable rather than only implied by the boolean
    `triggered` flag.

    `acquisition_plan` (issue #69 Stage 4) is Core's resolved candidate
    disposition plan for this run's own federated-discovery candidates --
    still only a plan, never an acquired source or Evidence Record (see
    this module's own docstring). `acquisition_plan_attempted` is `True`
    only when the request actually ran (whether it succeeded or failed);
    `acquisition_plan_skipped_reason` explains why it was not attempted
    (disabled by policy, no federated-discovery result to plan against, no
    candidates, or no `research_question_id`) and is `None` whenever
    `acquisition_plan_attempted` is `True`.
    """

    triggered: bool
    trigger_reason: str
    evidence_record_coverage: int
    federated_discovery: FederatedDiscoveryResult | None = None
    federated_discovery_error: str | None = None
    federated_discovery_attempted: bool = False
    citation_snowball_seed_dois: tuple[str, ...] = field(default_factory=tuple)
    citation_snowball: CitationSnowballResult | None = None
    citation_snowball_error: str | None = None
    citation_snowball_skipped_reason: str | None = None
    acquisition_plan: GeneralQuestionAcquisitionPlanResult | None = None
    acquisition_plan_error: str | None = None
    acquisition_plan_attempted: bool = False
    acquisition_plan_skipped_reason: str | None = None


def evaluate_and_run_discovery_augmentation(
    *,
    session_repository: SessionRepository,
    session_id: str,
    workflow_result: WorkflowResult,
    policy: FederatedDiscoveryPolicy,
    execution_budget: ExecutionBudget | None,
    research_question_id: str | None = None,
) -> DiscoveryAugmentationResult:
    """Evaluate the coverage-gap trigger and run the bounded steps it authorizes.

    Never raises: a `KeCommandError` (Core not installed, provider
    failure, malformed output -- already sanitized by `ke_client.py`) or an
    exhausted shared `execution_budget` is caught and recorded as this
    step's own failure/skip reason, the same "record what happened, do not
    let one failure hide another" posture `run_fixed_evidence_workflow`
    already established. Each attempted sub-step appends exactly one
    `ResearchEvent`, whether it succeeds, fails, or is skipped for a
    resolvable reason -- durable workflow history either way.

    `research_question_id`, when supplied, is forwarded to the
    federated-discovery sub-step (never citation-snowball -- see
    `docs/roadmap/answer_session_versioning_design.md`'s "Citation-snowball
    is out of scope for this threading") so a later freshness check can find
    this run via `ke_client.federated_discover_history`, and also to the
    acquisition-plan sub-step (issue #69 Stage 4), which requires one and is
    skipped without it. Defaulting to `None` preserves every existing
    caller's behavior exactly.
    """

    parallel_retrieval = workflow_result.parallel_retrieval
    coverage = _evidence_record_coverage(parallel_retrieval)

    if parallel_retrieval is not None and parallel_retrieval.primary.error is not None:
        return DiscoveryAugmentationResult(
            triggered=False,
            trigger_reason=(
                "Primary corpus retrieval failed; federated discovery was not attempted "
                "-- broader provider coverage cannot fix a failed local retrieval call."
            ),
            evidence_record_coverage=coverage,
        )

    if coverage >= policy.min_evidence_record_coverage:
        return DiscoveryAugmentationResult(
            triggered=False,
            trigger_reason=(
                f"Evidence-record coverage ({coverage}) met the configured threshold "
                f"({policy.min_evidence_record_coverage}); federated discovery was not needed."
            ),
            evidence_record_coverage=coverage,
        )

    trigger_reason = (
        f"Evidence-record coverage ({coverage}) fell below the configured threshold "
        f"({policy.min_evidence_record_coverage}); broadening the search."
    )

    federated_result: FederatedDiscoveryResult | None = None
    federated_error: str | None = None
    if policy.enable_federated_discovery:
        federated_result, federated_error = _run_federated_discovery(
            session_repository=session_repository,
            session_id=session_id,
            question=workflow_result.question,
            policy=policy,
            execution_budget=execution_budget,
            research_question_id=research_question_id,
        )

    (
        acquisition_plan_result,
        acquisition_plan_error,
        acquisition_plan_attempted,
        acquisition_plan_skipped_reason,
    ) = _maybe_run_acquisition_plan(
        session_repository=session_repository,
        session_id=session_id,
        federated_result=federated_result,
        policy=policy,
        execution_budget=execution_budget,
        research_question_id=research_question_id,
    )

    seed_dois = _seed_dois(workflow_result, policy)
    snowball_result: CitationSnowballResult | None = None
    snowball_error: str | None = None
    snowball_skipped_reason: str | None = None
    if not policy.enable_citation_snowball:
        snowball_skipped_reason = "Citation-snowball is disabled by policy."
    elif not seed_dois:
        snowball_skipped_reason = (
            "No DOI-bearing paper in the primary retrieval branch to seed a citation-snowball "
            "expansion from."
        )
    else:
        snowball_result, snowball_error = _run_citation_snowball(
            session_repository=session_repository,
            session_id=session_id,
            seed_dois=seed_dois,
            policy=policy,
            execution_budget=execution_budget,
        )

    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason=trigger_reason,
        evidence_record_coverage=coverage,
        federated_discovery=federated_result,
        federated_discovery_error=federated_error,
        federated_discovery_attempted=policy.enable_federated_discovery,
        citation_snowball_seed_dois=seed_dois,
        citation_snowball=snowball_result,
        citation_snowball_error=snowball_error,
        citation_snowball_skipped_reason=snowball_skipped_reason,
        acquisition_plan=acquisition_plan_result,
        acquisition_plan_error=acquisition_plan_error,
        acquisition_plan_attempted=acquisition_plan_attempted,
        acquisition_plan_skipped_reason=acquisition_plan_skipped_reason,
    )


def _evidence_record_coverage(parallel_retrieval: ParallelRetrievalResult | None) -> int:
    """The deduplicated evidence-record count the trigger decision is based on.

    Union of the primary and contradiction-oriented branches' evidence
    record IDs -- the same recall-gain signal AI-O5 already computes on
    `ParallelRetrievalResult`, reused rather than re-derived. `0` when
    retrieval has not run at all (defensive; `run_fixed_evidence_workflow`
    always runs retrieval, so this is not expected in practice).
    """

    if parallel_retrieval is None:
        return 0
    return len(
        parallel_retrieval.primary_evidence_record_ids
        | parallel_retrieval.contradiction_evidence_record_ids
    )


def _seed_dois(
    workflow_result: WorkflowResult, policy: FederatedDiscoveryPolicy
) -> tuple[str, ...]:
    """DOIs of the primary branch's ranked papers, in rank order, deduplicated, capped.

    Deliberately drawn from the local corpus's own already-retrieved,
    already-relevant papers -- "seed known landmark work" -- rather than
    from federated-discovery candidates, which are unvetted leads this
    project does not treat as a citation-graph seed source.
    """

    report = workflow_result.evidence_report
    if report is None:
        return ()
    seen: dict[str, None] = {}
    for paper in report.papers:
        doi = paper.doi.strip()
        if doi and doi not in seen:
            seen[doi] = None
        if len(seen) >= policy.citation_snowball_seed_limit:
            break
    return tuple(seen)


def _run_federated_discovery(
    *,
    session_repository: SessionRepository,
    session_id: str,
    question: str,
    policy: FederatedDiscoveryPolicy,
    execution_budget: ExecutionBudget | None,
    research_question_id: str | None = None,
) -> tuple[FederatedDiscoveryResult | None, str | None]:
    start = time.monotonic()
    try:
        sub_budget = _sub_budget(policy.discovery_max_execution_seconds, execution_budget)
        plan = compile_discovery_plan(
            question,
            providers=policy.discovery_providers,
            limit_per_provider=policy.discovery_limit_per_provider,
            max_execution_seconds=sub_budget.remaining_seconds(),
        )
        result = execute_discovery_plan(
            plan,
            ledger_root=policy.ledger_root,
            openalex_api_key=policy.openalex_api_key,
            semantic_scholar_api_key=policy.semantic_scholar_api_key,
            research_question_id=research_question_id,
            ke_executable=policy.ke_executable,
        )
    except (DiscoveryPlanError, KeCommandError, ExecutionBudgetExceeded) as exc:
        error = str(exc)
        _record_event(
            session_repository,
            session_id=session_id,
            workflow_node=_FEDERATED_DISCOVERY_NODE,
            tool_name="ke federated-discover",
            output=None,
            error=error,
            duration_ms=_elapsed_ms(start),
        )
        return None, error

    _record_event(
        session_repository,
        session_id=session_id,
        workflow_node=_FEDERATED_DISCOVERY_NODE,
        tool_name="ke federated-discover",
        output=_federated_discovery_summary(result),
        error=None,
        duration_ms=_elapsed_ms(start),
        output_hash=_hash_candidates(candidate.canonical_id for candidate in result.candidates),
    )
    return result, None


def _run_citation_snowball(
    *,
    session_repository: SessionRepository,
    session_id: str,
    seed_dois: tuple[str, ...],
    policy: FederatedDiscoveryPolicy,
    execution_budget: ExecutionBudget | None,
) -> tuple[CitationSnowballResult | None, str | None]:
    start = time.monotonic()
    try:
        sub_budget = _sub_budget(policy.citation_snowball_max_execution_seconds, execution_budget)
        result = citation_snowball(
            seed_dois,
            ledger_root=policy.ledger_root,
            provider=policy.citation_snowball_provider,
            directions=policy.citation_snowball_directions,
            max_depth=policy.citation_snowball_max_depth,
            limit_per_traversal=policy.citation_snowball_limit_per_traversal,
            max_candidates=policy.citation_snowball_max_candidates,
            openalex_api_key=policy.openalex_api_key,
            semantic_scholar_api_key=policy.semantic_scholar_api_key,
            ke_executable=policy.ke_executable,
            execution_budget=sub_budget,
        )
    except (KeCommandError, ExecutionBudgetExceeded) as exc:
        error = str(exc)
        _record_event(
            session_repository,
            session_id=session_id,
            workflow_node=_CITATION_SNOWBALL_NODE,
            tool_name="ke citation-snowball",
            output=None,
            error=error,
            duration_ms=_elapsed_ms(start),
        )
        return None, error

    _record_event(
        session_repository,
        session_id=session_id,
        workflow_node=_CITATION_SNOWBALL_NODE,
        tool_name="ke citation-snowball",
        output=_citation_snowball_summary(result),
        error=None,
        duration_ms=_elapsed_ms(start),
        output_hash=_hash_candidates(candidate.canonical_id for candidate in result.candidates),
    )
    return result, None


def _maybe_run_acquisition_plan(
    *,
    session_repository: SessionRepository,
    session_id: str,
    federated_result: FederatedDiscoveryResult | None,
    policy: FederatedDiscoveryPolicy,
    execution_budget: ExecutionBudget | None,
    research_question_id: str | None,
) -> tuple[GeneralQuestionAcquisitionPlanResult | None, str | None, bool, str | None]:
    """Issue #69 Stage 4: request a bounded acquisition plan for this run's own candidates.

    Gated on a federated-discovery result already having run for this
    session with its own candidates -- Core's acquisition-plan command
    resolves ``candidate_ids`` strictly against one persisted
    ``federated-discover`` search-run snapshot, so there is nothing to plan
    against otherwise. Also gated on ``policy.enable_acquisition_plan``
    (default `False` -- see this module's own docstring for why this one
    toggle is off by default unlike the two above it) and on a
    ``research_question_id`` being available (Core's command requires one).

    Returns ``(plan, error, attempted, skipped_reason)``. ``attempted`` is
    `True` only when the request actually ran, whether it succeeded or
    failed; when `False`, ``plan`` and ``error`` are both `None` and
    ``skipped_reason`` names exactly why. Never raises: a `KeCommandError`
    or an exhausted shared ``execution_budget`` is caught and recorded as
    this step's own failure, the same posture every other sub-step in this
    module already follows.
    """

    if not policy.enable_acquisition_plan:
        return None, None, False, "Acquisition-plan requests are disabled by policy."
    if federated_result is None:
        return (
            None,
            None,
            False,
            "Federated discovery did not produce a result this run; nothing to request an "
            "acquisition plan against.",
        )
    if not federated_result.candidates:
        return (
            None,
            None,
            False,
            f"Federated discovery (search_run_id={federated_result.search_run_id}) returned "
            "no candidates; nothing to request an acquisition plan for.",
        )
    if not research_question_id:
        return (
            None,
            None,
            False,
            "No research_question_id was available for this run; Core's acquisition-plan "
            "command requires one.",
        )

    candidate_ids = _acquisition_candidate_ids(federated_result, policy)

    start = time.monotonic()
    try:
        sub_budget = _sub_budget(
            float(policy.acquisition_plan_max_elapsed_seconds), execution_budget
        )
        plan = general_question_acquisition_plan(
            search_run_id=federated_result.search_run_id,
            research_question_id=research_question_id,
            candidate_ids=candidate_ids,
            ledger_root=policy.ledger_root,
            max_candidates=policy.acquisition_plan_max_candidates,
            max_full_text_acquisitions=policy.acquisition_plan_max_full_text_acquisitions,
            max_elapsed_seconds=policy.acquisition_plan_max_elapsed_seconds,
            allow_metadata_only=policy.acquisition_plan_allow_metadata_only,
            ke_executable=policy.ke_executable,
            execution_budget=sub_budget,
        )
    except (KeCommandError, ExecutionBudgetExceeded) as exc:
        error = str(exc)
        _record_event(
            session_repository,
            session_id=session_id,
            workflow_node=_ACQUISITION_PLAN_NODE,
            tool_name="ke general-question-acquisition-plan",
            output=None,
            error=error,
            duration_ms=_elapsed_ms(start),
        )
        return None, error, True, None

    _record_event(
        session_repository,
        session_id=session_id,
        workflow_node=_ACQUISITION_PLAN_NODE,
        tool_name="ke general-question-acquisition-plan",
        output=_acquisition_plan_summary(plan),
        error=None,
        duration_ms=_elapsed_ms(start),
        output_hash=_hash_candidates(candidate_ids),
    )
    return plan, None, True, None


def _acquisition_candidate_ids(
    federated_result: FederatedDiscoveryResult, policy: FederatedDiscoveryPolicy
) -> tuple[str, ...]:
    """Deduplicated candidate IDs from this run's own federated-discovery result, capped.

    Deliberately drawn only from this run's federated-discovery candidates,
    never citation-snowball's -- Core's command resolves candidate_ids
    strictly against the one search-run snapshot named by search_run_id,
    and citation-snowball candidates were never recorded against that run.
    Capped at ``policy.acquisition_plan_max_candidates``, the same bound
    passed as the request's own ``max_candidates`` field, so this never
    asks Core to resolve more candidates than the plan's own budget allows.
    """

    seen: dict[str, None] = {}
    for candidate in federated_result.candidates:
        if candidate.canonical_id not in seen:
            seen[candidate.canonical_id] = None
        if len(seen) >= policy.acquisition_plan_max_candidates:
            break
    return tuple(seen)


def _acquisition_plan_summary(plan: GeneralQuestionAcquisitionPlanResult) -> str:
    return (
        f"search_run_id={plan.search_run_id} resolved={plan.resolved_candidate_count} "
        f"already_indexed={plan.already_indexed_count} "
        f"full_text_eligible={plan.full_text_selected_count} "
        f"metadata_only={plan.metadata_only_count} "
        f"skipped_budget={plan.skipped_budget_count} "
        f"not_in_run={plan.missing_candidate_count}. "
        "Plan only -- no full text was downloaded and nothing was acquired or ingested."
    )


def _sub_budget(
    policy_max_execution_seconds: float, execution_budget: ExecutionBudget | None
) -> ExecutionBudget:
    """Build this sub-step's own budget: the policy's bound, capped by any shared remaining time.

    Raises `ExecutionBudgetExceeded` immediately if the shared session
    budget is already exhausted, rather than silently handing the
    sub-step a fresh, unbounded clock -- a compiled plan's budget must
    never be silently widened by whoever executes it (`discovery_plan.py`'s
    own documented rule), and the shared session budget must never be
    silently ignored either.
    """

    remaining = policy_max_execution_seconds
    if execution_budget is not None:
        remaining = min(remaining, execution_budget.remaining_seconds())
    return ExecutionBudget.from_timeout(remaining)


def _federated_discovery_summary(result: FederatedDiscoveryResult) -> str:
    return (
        f"search_run_id={result.search_run_id} completeness={result.completeness} "
        f"{len(result.candidates)} deduplicated candidate(s) "
        f"across {len(result.provider_statuses)} provider(s) attempted. "
        "Discovery leads only -- not Evidence Records, not acquired, not synthesized from."
    )


def _citation_snowball_summary(result: CitationSnowballResult) -> str:
    truncated = " (truncated at max_candidates)" if result.truncated else ""
    return (
        f"snowball_run_id={result.snowball_run_id} completeness={result.completeness}"
        f"{truncated} {len(result.candidates)} discovered candidate(s) from "
        f"{len(result.seed_identifiers)} seed(s). "
        "Discovery leads only -- not Evidence Records, not acquired, not synthesized from."
    )


def _record_event(
    session_repository: SessionRepository,
    *,
    session_id: str,
    workflow_node: str,
    tool_name: str,
    output: str | None,
    error: str | None,
    duration_ms: int,
    output_hash: str | None = None,
) -> None:
    # `source_ids` is deliberately left empty: it is `SessionTrace`'s "what
    # evidence supported the output" signal, and a discovery/snowball
    # candidate is not an Evidence Record -- see this module's docstring.
    session_repository.append_event(
        ResearchEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=_timestamp(),
            workflow_node=workflow_node,
            executor_type=_EXECUTOR_TYPE,
            validation_status="succeeded" if error is None else "failed",
            output_hash=output_hash,
            tool_name=tool_name,
            notes=error if error is not None else output,
            duration_ms=duration_ms,
        )
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _hash_candidates(canonical_ids: Iterable[str]) -> str:
    payload = json.dumps({"canonical_ids": sorted(canonical_ids)}, sort_keys=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


__all__ = [
    "DEFAULT_ACQUISITION_PLAN_ALLOW_METADATA_ONLY",
    "DEFAULT_ACQUISITION_PLAN_MAX_CANDIDATES",
    "DEFAULT_ACQUISITION_PLAN_MAX_ELAPSED_SECONDS",
    "DEFAULT_ACQUISITION_PLAN_MAX_FULL_TEXT_ACQUISITIONS",
    "DEFAULT_DISCOVERY_LIMIT_PER_PROVIDER",
    "DEFAULT_DISCOVERY_MAX_EXECUTION_SECONDS",
    "DEFAULT_MIN_EVIDENCE_RECORD_COVERAGE",
    "DEFAULT_SNOWBALL_LIMIT_PER_TRAVERSAL",
    "DEFAULT_SNOWBALL_MAX_CANDIDATES",
    "DEFAULT_SNOWBALL_MAX_DEPTH",
    "DEFAULT_SNOWBALL_MAX_EXECUTION_SECONDS",
    "DEFAULT_SNOWBALL_SEED_LIMIT",
    "DiscoveryAugmentationResult",
    "DiscoveryPolicyError",
    "FederatedDiscoveryPolicy",
    "evaluate_and_run_discovery_augmentation",
]
