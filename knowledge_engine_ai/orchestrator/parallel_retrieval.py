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

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from knowledge_engine_ai.ke_client import KeCommandError, enriched_evidence_report
from knowledge_engine_ai.models import EvidenceReport

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
) -> ParallelRetrievalResult:
    """Run primary retrieval and contradiction-oriented retrieval concurrently.

    Never raises on a single branch's `KeCommandError` -- each branch's
    outcome (report or error message) is captured in the returned
    `ParallelRetrievalResult` so a caller sees exactly what happened on
    both sides, the same "record what happened, do not let one failure
    hide another" posture `run_fixed_evidence_workflow` already
    established for its own fixed steps. `external_discovery`, if
    supplied, runs in the same thread pool; its own exception is caught
    and reported via `external_discovery_error`, never propagated.
    """

    contradiction_query = build_contradiction_query(question)

    with ThreadPoolExecutor(max_workers=3) as executor:
        primary_future = executor.submit(
            _run_branch,
            query=question,
            sources=sources,
            evidence=evidence,
            limit=limit,
            ke_executable=ke_executable,
        )
        contradiction_future = executor.submit(
            _run_branch,
            query=contradiction_query,
            sources=sources,
            evidence=evidence,
            limit=limit,
            ke_executable=ke_executable,
        )
        external_future = None
        if external_discovery is not None:
            external_future = executor.submit(external_discovery, question)

        primary = primary_future.result()
        contradiction = contradiction_future.result()

        external_discovery_result: object | None = None
        external_discovery_error: str | None = None
        if external_future is not None:
            try:
                external_discovery_result = external_future.result()
            except Exception as exc:  # noqa: BLE001 -- caller-supplied callable, any exception possible
                external_discovery_error = str(exc)

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


def _run_branch(
    *,
    query: str,
    sources: Path,
    evidence: Path,
    limit: int,
    ke_executable: str,
) -> RetrievalBranchResult:
    try:
        report = enriched_evidence_report(
            query, sources=sources, evidence=evidence, limit=limit, ke_executable=ke_executable
        )
        return RetrievalBranchResult(query=query, report=report, error=None)
    except KeCommandError as exc:
        return RetrievalBranchResult(query=query, report=None, error=str(exc))


def _evidence_record_ids(report: EvidenceReport | None) -> frozenset[str]:
    if report is None:
        return frozenset()
    return frozenset(
        record.evidence_record_id
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    )
