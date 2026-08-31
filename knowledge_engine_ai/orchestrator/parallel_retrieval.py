"""AI-O5: run primary retrieval and contradiction-oriented retrieval in parallel.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O5 milestone: "Run
primary retrieval, contradiction-oriented retrieval, and optional
external discovery in parallel." Success criterion: "measured
contradiction recall improves without materially reducing precision."

This module adds a second, deliberately differently-worded retrieval
call alongside AI-O3's existing single `enriched_evidence_report(question,
...)` call -- not a new retrieval mechanism inside `core` (there is
none to build; `ke evidence-report`'s fused lexical+vector search is the
only retrieval primitive `core` exposes, per `core_interface_contract.md`),
but a second *query* against that same primitive, phrased to surface
evidence that might contradict the primary question rather than confirm
it. `core` itself already validated this exact technique: the
oncology/mental-health "same-PICO contradiction search" audits
(`docs/oncology_same_pico_contradiction_search_audit.md`,
`docs/mental_health_same_pico_contradiction_search_audit.md` in
`knowledge-engine-core`) screened every committed Evidence Record's text
for a fixed negative-signal phrase set ("no significant", "not
significant", "no difference", "did not", "failed to", "no benefit", "no
improvement", "worse survival/outcome", "inferior", "shorter overall
survival/progression-free survival/survival", "increased mortality/risk
of death", "higher risk of death") and found this deterministic
vocabulary a reliable way to surface contradiction candidates for human
(here, automated) follow-up. `CONTRADICTION_SIGNAL_PHRASES` below is
that exact, already-validated phrase set, reused rather than
independently reinvented -- appending it to the question turns `ke
evidence-report`'s existing fused search into a second, differently-biased
retrieval pass over the same corpus, with no new `core`-side capability
and no LLM call, matching AI-O3's "no LLM dynamically deciding execution"
precedent (AI-O6, not this milestone, is where independent verification
first requires a model).

Both retrieval calls run concurrently via a thread pool -- each is an
I/O-bound `ke` subprocess call (see `ke_client.py`'s docstring on why
this project always shells out rather than importing `core` directly),
so threads, not `asyncio` or multiprocessing, are the right concurrency
primitive here. Each branch's failure is captured independently rather
than allowed to abort the other, the same "one step's failure does not
stop the remaining fixed steps" discipline AI-O3's `run_fixed_evidence_workflow`
already established.

BT-5a adds conservative process-local reuse around those successful
indexed retrievals. A cached branch is reusable only when the normalized
query, limit, source/evidence file revisions, paths, working directory,
and Core executable all match. Failed retrievals are never cached, and a
content change automatically produces a different key. External discovery
still runs independently even when both indexed branches are cache hits.

External discovery is optional and, in this first cut, deliberately
unwired to any concrete `core` capability: the only real external-discovery
command `core` exposes, `ke discovery-cycle-run`, advances a persisted
pagination offset (`--state`) on every call and is designed for a
scheduled, corpus-growth cadence, not a per-question, in-session lookup
-- calling it here would silently mutate that offset as a side effect of
answering one question, which is not what "optional external discovery
in parallel" asks for. `external_discovery` therefore accepts an
injectable callable (dependency injection, not a hardcoded call), left
`None` by default; a future milestone that builds a genuinely
per-question-safe external-lookup primitive in `core` can supply one
without this module changing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded
from knowledge_engine_ai.ke_client import KeCommandError, enriched_evidence_report
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.retrieval_cache import (
    build_retrieval_cache_key,
    get_cached_retrieval_report,
    store_cached_retrieval_report,
)

CONTRADICTION_SIGNAL_PHRASES: tuple[str, ...] = (
    "no significant",
    "not significant",
    "no difference",
    "did not",
    "failed to",
    "no benefit",
    "no improvement",
    "worse survival",
    "worse outcome",
    "inferior",
    "shorter overall survival",
    "shorter progression-free survival",
    "shorter survival",
    "increased mortality",
    "increased risk of death",
    "higher risk of death",
)
"""The negative-signal phrase set `knowledge-engine-core`'s own
same-PICO contradiction-search audits already validated
(oncology: 1,534 records screened, 108 matched, 1 genuine `contradicts`
candidate investigated in full; mental health: 133 records screened,
17 matched, 0 same-PICO contradictions found). Reused verbatim here as
a query-reformulation vocabulary, not re-derived -- see this module's
docstring."""


class ExternalDiscoveryError(RuntimeError):
    """The caller-supplied external-discovery callable raised."""


ExternalDiscoveryCallable = Callable[[str], object]


@dataclass(frozen=True)
class RetrievalBranchResult:
    """One retrieval branch's outcome -- always recorded, whether it succeeded or not."""

    query: str
    report: EvidenceReport | None
    error: str | None
    cache_hit: bool = False


@dataclass(frozen=True)
class ParallelRetrievalResult:
    """The assembled result of running primary and contradiction-oriented retrieval together.

    `contradiction_only_evidence_record_ids` is the concrete recall
    signal AI-O5's success criterion asks to measure: evidence records
    the contradiction-oriented query surfaced that the primary query did
    not, i.e. the retrieval headroom parallel retrieval actually gained.
    """

    question: str
    primary: RetrievalBranchResult
    contradiction: RetrievalBranchResult
    external_discovery_result: object | None
    external_discovery_error: str | None
    primary_evidence_record_ids: frozenset[str]
    contradiction_evidence_record_ids: frozenset[str]
    contradiction_only_evidence_record_ids: frozenset[str]


def build_contradiction_query(question: str) -> str:
    """Append the validated negative-signal phrase set to `question`.

    A plain string concatenation, not a boolean query-language
    expression: `ke evidence-report`'s fused lexical+vector search
    consumes free text, so widening the search terms (rather than
    constructing an OR-expression `core` does not parse) is the correct
    way to bias one retrieval pass toward contradiction-signal language
    while leaving the underlying search primitive unchanged.
    """

    normalized = question.strip()
    if not normalized:
        raise ValueError("Question must not be empty.")
    return f"{normalized} {' '.join(CONTRADICTION_SIGNAL_PHRASES)}"


def run_parallel_retrieval(
    question: str,
    *,
    sources: Path,
    evidence: Path,
    limit: int = 5,
    external_discovery: ExternalDiscoveryCallable | None = None,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> ParallelRetrievalResult:
    """Run primary retrieval and contradiction-oriented retrieval concurrently.

    Never raises on a single branch's `KeCommandError` -- each branch's
    outcome (report or error message) is captured in the returned
    `ParallelRetrievalResult` so a caller sees exactly what happened on
    both sides, the same "record what happened, do not let one failure
    hide another" posture `run_fixed_evidence_workflow` already
    established for its own fixed steps.

    `external_discovery`, if supplied, runs on its own daemon thread
    rather than inside the retrieval thread pool. The primary and
    contradiction branches are already bounded by `execution_budget`
    (it becomes each `ke` subprocess call's own timeout, same as every
    other `ke_client` call); a caller-supplied `external_discovery`
    callable has no such built-in bound, so this function enforces one
    directly: when `execution_budget` is supplied, the wait for that
    callback is capped at the budget's own remaining time (mirroring
    `_run_ke_command`'s `execution_budget.remaining_seconds()` pattern),
    and a callback that has not finished by then is abandoned -- its
    error is reported via `external_discovery_error`, its eventual
    result (if any) is discarded, and this call returns rather than
    blocking further. This is what lets a caller reserve a synthesis
    time floor (`run_research_question`'s `min_synthesis_seconds`,
    BT-4/issue #87) without a slow external-discovery callback silently
    consuming that reserved tail. The thread itself cannot be forcibly
    killed (Python threads never can be); marking it a daemon thread
    only ensures it cannot block interpreter/process shutdown either.
    Without `execution_budget`, the wait remains unbounded, matching
    this function's pre-existing behavior for callers that configure no
    timeout at all.
    """

    contradiction_query = build_contradiction_query(question)

    external_done = threading.Event()
    external_result_holder: list[object] = []
    external_error_holder: list[str] = []
    external_thread: threading.Thread | None = None
    if external_discovery is not None:
        external_thread = threading.Thread(
            target=_run_external_discovery,
            args=(
                external_discovery,
                question,
                external_result_holder,
                external_error_holder,
                external_done,
            ),
            name="parallel-retrieval-external-discovery",
            daemon=True,
        )
        external_thread.start()

    with ThreadPoolExecutor(max_workers=2) as executor:
        primary_future = executor.submit(
            _run_branch,
            query=question,
            sources=sources,
            evidence=evidence,
            limit=limit,
            ke_executable=ke_executable,
            execution_budget=execution_budget,
        )
        contradiction_future = executor.submit(
            _run_branch,
            query=contradiction_query,
            sources=sources,
            evidence=evidence,
            limit=limit,
            ke_executable=ke_executable,
            execution_budget=execution_budget,
        )

        primary = primary_future.result()
        contradiction = contradiction_future.result()

    external_discovery_result: object | None = None
    external_discovery_error: str | None = None
    if external_thread is not None:
        try:
            wait_timeout = (
                execution_budget.remaining_seconds() if execution_budget is not None else None
            )
        except ExecutionBudgetExceeded:
            wait_timeout = 0.0
        completed = external_done.wait(timeout=wait_timeout)
        if not completed:
            external_discovery_error = (
                "External discovery callback did not complete within the execution budget "
                f"(waited {wait_timeout:.3f}s); it was abandoned and its eventual result, "
                "if any, will not be used."
            )
        elif external_error_holder:
            external_discovery_error = external_error_holder[0]
        elif external_result_holder:
            external_discovery_result = external_result_holder[0]

    primary_ids = _evidence_record_ids(primary.report)
    contradiction_ids = _evidence_record_ids(contradiction.report)

    return ParallelRetrievalResult(
        question=question,
        primary=primary,
        contradiction=contradiction,
        external_discovery_result=external_discovery_result,
        external_discovery_error=external_discovery_error,
        primary_evidence_record_ids=primary_ids,
        contradiction_evidence_record_ids=contradiction_ids,
        contradiction_only_evidence_record_ids=contradiction_ids - primary_ids,
    )


def _run_external_discovery(
    external_discovery: ExternalDiscoveryCallable,
    question: str,
    result_holder: list[object],
    error_holder: list[str],
    done: threading.Event,
) -> None:
    """Run the caller-supplied callback on its own thread and always signal `done`.

    Runs on a daemon thread started by `run_parallel_retrieval`, which waits on
    `done` for at most its own bounded timeout -- so this function's own
    unbounded runtime never directly blocks that caller; only the `done.set()`
    signal in `finally` communicates back, and a run that never finishes simply
    never sets `done`.
    """

    try:
        result_holder.append(external_discovery(question))
    except Exception as exc:  # noqa: BLE001 -- caller-supplied callable, any exception possible
        error_holder.append(str(exc))
    finally:
        done.set()


def _run_branch(
    *,
    query: str,
    sources: Path,
    evidence: Path,
    limit: int,
    ke_executable: str,
    execution_budget: ExecutionBudget | None,
) -> RetrievalBranchResult:
    cache_key = build_retrieval_cache_key(
        query,
        sources=sources,
        evidence=evidence,
        limit=limit,
        ke_executable=ke_executable,
    )
    cached_report = get_cached_retrieval_report(cache_key)
    if cached_report is not None:
        return RetrievalBranchResult(
            query=query,
            report=cached_report,
            error=None,
            cache_hit=True,
        )

    try:
        report = enriched_evidence_report(
            query,
            sources=sources,
            evidence=evidence,
            limit=limit,
            ke_executable=ke_executable,
            execution_budget=execution_budget,
        )
    except KeCommandError as exc:
        return RetrievalBranchResult(query=query, report=None, error=str(exc))

    store_cached_retrieval_report(cache_key, report)
    return RetrievalBranchResult(query=query, report=report, error=None, cache_hit=False)


def _evidence_record_ids(report: EvidenceReport | None) -> frozenset[str]:
    if report is None:
        return frozenset()
    return frozenset(
        record.evidence_record_id
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    )
