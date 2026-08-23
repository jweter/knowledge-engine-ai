"""Subprocess wrapper for `core`'s `ke` CLI -- the documented interface boundary.

Never imports `knowledge_engine` as a Python package: `core_interface_contract.md`
is explicit that "there is no HTTP API, no RPC layer, no Python package
published for import today -- `ke <command>` is the interface," and
importing it directly would pull in `core`'s full dependency set (`torch`,
`sentence-transformers`, `faiss-cpu`) for a project that only needs to
invoke one CLI command. See `docs/ai_design.md`'s "shell out to `ke`"
decision. Every call runs `ke` as a subprocess with an explicit argument
list -- never `shell=True`, never string-interpolated arguments.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from knowledge_engine_ai.execution import ExecutionBudget, ExecutionBudgetExceeded
from knowledge_engine_ai.models import (
    EvidenceIntelligence,
    EvidenceIntelligenceParseError,
    EvidenceReport,
    EvidenceReportParseError,
    parse_evidence_intelligence,
    parse_evidence_report,
)


class KeCommandError(RuntimeError):
    """`ke` exited non-zero or produced output this project could not parse."""


_NO_GRAPH_CLAIM_MARKER = "No graph claim found"


def _resolve_ke_executable(ke_executable: str) -> str:
    """Resolve `ke_executable` to a real path via a PATHEXT-aware `PATH` search.

    Windows's `CreateProcess` (what `subprocess.run` uses under the hood)
    only auto-appends `.exe` when locating a bare command name -- it does
    not consult `PATHEXT` the way a shell or `shutil.which` does. Poetry's
    generated Windows entry point for `ke` is `ke.cmd`, not `ke.exe`, so
    an unresolved `subprocess.run(["ke", ...])` silently fails to find it
    there (`FileNotFoundError`), even with core correctly installed and
    core's venv `Scripts` directory on `PATH`. `shutil.which` performs the
    correct search on every platform and is a safe no-op on POSIX, where
    this was never an issue. Falls back to the original string unresolved
    if not found, so the existing `FileNotFoundError` handling below still
    raises its clear "is knowledge-engine-core installed and on PATH?"
    error instead of a new failure mode.
    """

    return shutil.which(ke_executable) or ke_executable


def _run_ke_command(
    command: list[str],
    *,
    operation: str,
    execution_budget: ExecutionBudget | None,
    working_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one Core command inside the shared wall-clock budget."""

    try:
        timeout = execution_budget.remaining_seconds() if execution_budget is not None else None
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=working_directory,
        )
    except (ExecutionBudgetExceeded, subprocess.TimeoutExpired) as exc:
        raise KeCommandError(
            f"`{operation}` exceeded the configured execution time limit."
        ) from exc


def evidence_report(
    question: str,
    *,
    sources: Path,
    evidence: Path,
    limit: int = 5,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
    working_directory: Path | None = None,
) -> EvidenceReport:
    """Run `ke evidence-report <question> --format json` and return the parsed result.

    ``working_directory`` selects the Core project root whose local database
    the CLI should use. Leaving it unset preserves the normal caller working
    directory. Raises `KeCommandError` on command or contract failure and
    never returns a partial or guessed result.
    """

    command = [
        _resolve_ke_executable(ke_executable),
        "evidence-report",
        question,
        "--sources",
        str(sources),
        "--evidence",
        str(evidence),
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    try:
        result = _run_ke_command(
            command,
            operation="ke evidence-report",
            execution_budget=execution_budget,
            working_directory=working_directory,
        )
    except FileNotFoundError as exc:
        raise KeCommandError(
            f"Could not run {ke_executable!r} -- is knowledge-engine-core installed and on PATH?"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise KeCommandError(f"`ke evidence-report` exited {result.returncode}: {message}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise KeCommandError(f"`ke evidence-report` did not return valid JSON: {exc}") from exc

    try:
        return parse_evidence_report(payload)
    except EvidenceReportParseError as exc:
        raise KeCommandError(str(exc)) from exc


def evidence_intelligence(
    evidence_record_id: str,
    *,
    evidence: Path,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> EvidenceIntelligence | None:
    """Run `ke evidence-intelligence --format json` and return the parsed result.

    Returns `None`, not an error, when the record has no graph claim yet
    (`ke graph-build` has not processed it) -- an expected, common state
    for a record `evidence_report` just matched, not a failure. Still
    raises `KeCommandError` for every other failure (`ke` not installed,
    invalid JSON, an unparseable schema, or any other non-zero exit) --
    never silently swallows a real error alongside the expected one.
    """

    command = [
        _resolve_ke_executable(ke_executable),
        "evidence-intelligence",
        "--evidence",
        str(evidence),
        "--evidence-record-id",
        evidence_record_id,
        "--format",
        "json",
    ]
    try:
        result = _run_ke_command(
            command, operation="ke evidence-intelligence", execution_budget=execution_budget
        )
    except FileNotFoundError as exc:
        raise KeCommandError(
            f"Could not run {ke_executable!r} -- is knowledge-engine-core installed and on PATH?"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        if _NO_GRAPH_CLAIM_MARKER in message:
            return None
        raise KeCommandError(f"`ke evidence-intelligence` exited {result.returncode}: {message}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise KeCommandError(
            f"`ke evidence-intelligence` did not return valid JSON: {exc}"
        ) from exc

    try:
        return parse_evidence_intelligence(payload)
    except EvidenceIntelligenceParseError as exc:
        raise KeCommandError(str(exc)) from exc


def evidence_map_report(
    map_path: Path,
    *,
    evidence: Path,
    relationships: Path,
    sources: Path,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> str:
    """Run `ke evidence-map-report` and return its rendered Markdown report verbatim.

    `ke evidence-map-report` has no `--format json` -- it renders a
    deterministic cross-study Markdown report from a curated,
    human-authored evidence map, evidence file, and relationship file,
    and there is no richer structured contract to parse here. Returns
    the report text as-is; raises `KeCommandError` on any non-zero
    exit (an invalid map, invalid evidence/relationships, or `ke` not
    installed) rather than a partial result.
    """

    command = [
        _resolve_ke_executable(ke_executable),
        "evidence-map-report",
        str(map_path),
        "--evidence",
        str(evidence),
        "--relationships",
        str(relationships),
        "--sources",
        str(sources),
    ]
    try:
        result = _run_ke_command(
            command, operation="ke evidence-map-report", execution_budget=execution_budget
        )
    except FileNotFoundError as exc:
        raise KeCommandError(
            f"Could not run {ke_executable!r} -- is knowledge-engine-core installed and on PATH?"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise KeCommandError(f"`ke evidence-map-report` exited {result.returncode}: {message}")

    return result.stdout


def statistical_verify(
    inputs_path: Path,
    *,
    evidence: Path,
    binary_inputs: Path | None = None,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> str:
    """Run `ke statistical-verify` and return its rendered Markdown report verbatim.

    Like `evidence_map_report`, there is no `--format json` for this
    command -- it verifies explicitly curated effect arithmetic against
    a curated statistical-inputs file and renders Markdown, nothing
    this project re-derives. Raises `KeCommandError` on any non-zero
    exit rather than a partial result.
    """

    command = [
        _resolve_ke_executable(ke_executable),
        "statistical-verify",
        str(inputs_path),
        "--evidence",
        str(evidence),
    ]
    if binary_inputs is not None:
        command += ["--binary-inputs", str(binary_inputs)]
    try:
        result = _run_ke_command(
            command, operation="ke statistical-verify", execution_budget=execution_budget
        )
    except FileNotFoundError as exc:
        raise KeCommandError(
            f"Could not run {ke_executable!r} -- is knowledge-engine-core installed and on PATH?"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise KeCommandError(f"`ke statistical-verify` exited {result.returncode}: {message}")

    return result.stdout


def enriched_evidence_report(
    question: str,
    *,
    sources: Path,
    evidence: Path,
    limit: int = 5,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> EvidenceReport:
    """Run `evidence_report`, then attach each matched record's Evidence Intelligence.

    Still retrieval plus already-computed, already-stored signals only --
    no synthesis, no new judgment. Each `EvidenceRecord` with an
    `evidence_record_id` gets one `evidence_intelligence` lookup; records
    without a graph claim yet simply carry `evidence_intelligence=None`
    (see `evidence_intelligence`'s own docstring), not an error.
    """

    report = evidence_report(
        question,
        sources=sources,
        evidence=evidence,
        limit=limit,
        ke_executable=ke_executable,
        execution_budget=execution_budget,
    )

    enriched_papers = []
    for paper in report.papers:
        enriched_records = []
        for record in paper.evidence_records:
            intelligence = None
            if record.evidence_record_id:
                intelligence = evidence_intelligence(
                    record.evidence_record_id,
                    evidence=evidence,
                    ke_executable=ke_executable,
                    execution_budget=execution_budget,
                )
            enriched_records.append(dataclasses.replace(record, evidence_intelligence=intelligence))
        enriched_papers.append(dataclasses.replace(paper, evidence_records=enriched_records))

    return dataclasses.replace(report, papers=enriched_papers)


class FederatedDiscoveryParseError(RuntimeError):
    """`ke federated-discover --output`'s JSON did not match the expected shape."""


@dataclasses.dataclass(frozen=True)
class FederatedProviderStatus:
    """One provider's outcome for one federated discovery run."""

    provider: str
    outcome: str
    attempted: bool
    result_count: int
    reason: str | None


@dataclasses.dataclass(frozen=True)
class FederatedProviderAssertion:
    """One provider-native metadata assertion from Core's disagreement report."""

    provider: str
    provider_id: str
    value: str | int | bool


@dataclasses.dataclass(frozen=True)
class FederatedProviderDisagreement:
    """Observed conflicting provider values for one metadata field."""

    field: str
    assertions: tuple[FederatedProviderAssertion, ...]


@dataclasses.dataclass(frozen=True)
class FederatedCandidateDisagreements:
    """Core-recorded metadata disagreements for one canonical candidate."""

    canonical_id: str
    disagreements: tuple[FederatedProviderDisagreement, ...]


@dataclasses.dataclass(frozen=True)
class FederatedProviderObservationFlags:
    """One provider's publication-status/preprint observation for one candidate.

    These are provider-native assertions, preserved per-provider like
    ``FederatedProviderAssertion`` above -- AI does not merge, vote on, or
    pick an authoritative value across providers. ``None`` means the
    provider did not report the flag, which is distinct from the provider
    reporting ``False``.

    ``retracted``/``corrected``/``expression_of_concern``/``withdrawn`` are
    four independent Core flags, not one status enum: a work may carry more
    than one at once, and a provider reporting one says nothing about the
    others.
    """

    provider: str
    retracted: bool | None
    preprint: bool | None
    preprint_version: int | None
    corrected: bool | None = None
    expression_of_concern: bool | None = None
    withdrawn: bool | None = None


@dataclasses.dataclass(frozen=True)
class FederatedCandidateSummary:
    """One Core-deduplicated federated discovery candidate for downstream display.

    Provider names are provenance only. ``canonical_id`` is Core-owned work
    identity; AI does not re-deduplicate candidates or select an authoritative
    provider observation.
    """

    canonical_id: str
    title: str
    doi: str | None
    publication_year: int | None
    providers: tuple[str, ...]
    observation_flags: tuple[FederatedProviderObservationFlags, ...] = ()


@dataclasses.dataclass(frozen=True)
class FederatedDiscoveryResult:
    """One `ke federated-discover --output` response, fully parsed and typed."""

    search_run_id: str
    query_text: str
    completeness: str
    provider_statuses: tuple[FederatedProviderStatus, ...]
    candidates: tuple[FederatedCandidateSummary, ...]
    provider_disagreements: tuple[FederatedCandidateDisagreements, ...] | None
    search_run_created_at: str | None


def parse_federated_discovery_result(payload: dict[str, Any]) -> FederatedDiscoveryResult:
    """Parse Core's public federated snapshot without guessing omitted facts.

    Provider disagreement is preserved as descriptive metadata-quality state.
    It is not interpreted as scientific contradiction, evidence strength, or a
    signal that one provider value is authoritative. Older snapshots that do
    not contain the disagreement report remain explicitly ``None`` rather than
    being misrepresented as an empty report.

    Each candidate's per-provider ``retracted``/``corrected``/
    ``expression_of_concern``/``withdrawn``/``preprint``/``preprint_version``
    observations (Core's ``ProviderObservation`` fields) are preserved as
    ``FederatedCandidateSummary.observation_flags``, one entry per provider
    observation, unmerged and unvoted-on across providers. A provider
    observation that omits these fields -- an older Core run, or a provider
    that does not report them -- parses to explicit ``None`` per field rather
    than a guessed ``False``, matching the same "absent is not negative"
    contract as provider disagreement above.

    Core's ``coverage.created_at`` (the search run's own recorded timestamp,
    documented in ``knowledge-engine-core``'s ``docs/core_interface_contract.md``
    as part of the public ``coverage`` block) is preserved as
    ``search_run_created_at``. An older payload that predates -- or a
    malformed payload that omits -- the ``coverage`` block parses this to
    ``None`` rather than raising, the same graceful-absence contract used for
    ``provider_disagreements`` above; this field is provenance, not a
    required part of the discovery result shape.
    """

    try:
        search_run_id = payload["search_run_id"]
        query_text = payload["query"]["text"]
        completeness = payload["completeness"]
        raw_statuses = payload["provider_statuses"]
        raw_candidates = payload["candidates"]
    except (KeyError, TypeError) as exc:
        raise FederatedDiscoveryParseError(
            f"`ke federated-discover --output` payload is missing a required field: {exc}"
        ) from exc

    raw_disagreement_report = payload.get("provider_disagreements")
    raw_coverage = payload.get("coverage")
    search_run_created_at = (
        raw_coverage.get("created_at") if isinstance(raw_coverage, dict) else None
    )

    try:
        provider_statuses = tuple(
            FederatedProviderStatus(
                provider=status["provider"],
                outcome=status["outcome"],
                attempted=status["attempted"],
                result_count=status["result_count"],
                reason=status.get("reason"),
            )
            for status in raw_statuses
        )
        candidates = tuple(
            FederatedCandidateSummary(
                canonical_id=candidate["canonical_id"],
                title=candidate["title"],
                doi=candidate.get("doi"),
                publication_year=candidate.get("publication_year"),
                providers=tuple(
                    sorted({observation["provider"] for observation in candidate["observations"]})
                ),
                observation_flags=tuple(
                    FederatedProviderObservationFlags(
                        provider=observation["provider"],
                        retracted=observation.get("retracted"),
                        preprint=observation.get("preprint"),
                        preprint_version=observation.get("preprint_version"),
                        corrected=observation.get("corrected"),
                        expression_of_concern=observation.get("expression_of_concern"),
                        withdrawn=observation.get("withdrawn"),
                    )
                    for observation in candidate["observations"]
                ),
            )
            for candidate in raw_candidates
        )
        provider_disagreements = None
        if raw_disagreement_report is not None:
            provider_disagreements = tuple(
                FederatedCandidateDisagreements(
                    canonical_id=candidate["canonical_id"],
                    disagreements=tuple(
                        FederatedProviderDisagreement(
                            field=disagreement["field"],
                            assertions=tuple(
                                FederatedProviderAssertion(
                                    provider=assertion["provider"],
                                    provider_id=assertion["provider_id"],
                                    value=assertion["value"],
                                )
                                for assertion in disagreement["assertions"]
                            ),
                        )
                        for disagreement in candidate["disagreements"]
                    ),
                )
                for candidate in raw_disagreement_report["candidates"]
            )
    except (KeyError, TypeError) as exc:
        raise FederatedDiscoveryParseError(
            f"`ke federated-discover --output` payload is malformed: {exc}"
        ) from exc

    return FederatedDiscoveryResult(
        search_run_id=search_run_id,
        query_text=query_text,
        completeness=completeness,
        provider_statuses=provider_statuses,
        candidates=candidates,
        provider_disagreements=provider_disagreements,
        search_run_created_at=search_run_created_at,
    )


def federated_discover(
    query: str,
    *,
    ledger_root: Path,
    limit: int = 20,
    providers: tuple[str, ...] | None = None,
    openalex_api_key: str | None = None,
    semantic_scholar_api_key: str | None = None,
    project_id: str | None = None,
    research_question_id: str | None = None,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> FederatedDiscoveryResult:
    """Run `ke federated-discover --output <tmp>` and return the parsed result.

    `ke federated-discover` has no `--format json` for stdout -- unlike
    `evidence_report` above, its structured output is written to
    `--output <path>` (a durable ledger under `--ledger-root` is the
    actual persisted record; `--output` is a convenience snapshot of this
    one run, per that command's own docstring). This wrapper writes that
    snapshot to a private temporary file, parses it, and discards the
    file -- the caller only sees the typed result. Raises `KeCommandError`
    on command or contract failure and never returns a partial or guessed
    result.

    `project_id`/`research_question_id` are optional internal run context,
    forwarded to Core's `--project-id`/`--research-question-id` flags (the
    FRD-6 follow-up that made them CLI-reachable). Neither value enters
    `FederatedDiscoveryResult` -- Core's own `SearchCoverageReport` never
    includes them in the public coverage payload (see that type's
    docstring in `knowledge-engine-core`) -- so a caller that wants a
    tagged run correlated later must retain `research_question_id` itself
    and pass it to `federated_discover_history` below. Omitting both
    preserves every existing call's behavior exactly.
    """

    with tempfile.TemporaryDirectory(prefix="ke-federated-discover-") as scratch_dir:
        output_path = Path(scratch_dir) / "result.json"
        command = [
            _resolve_ke_executable(ke_executable),
            "federated-discover",
            "--query",
            query,
            "--ledger-root",
            str(ledger_root),
            "--limit",
            str(limit),
            "--output",
            str(output_path),
        ]
        if providers:
            command += ["--providers", ",".join(providers)]
        if openalex_api_key:
            command += ["--openalex-api-key", openalex_api_key]
        if semantic_scholar_api_key:
            command += ["--semantic-scholar-api-key", semantic_scholar_api_key]
        if project_id:
            command += ["--project-id", project_id]
        if research_question_id:
            command += ["--research-question-id", research_question_id]

        try:
            result = _run_ke_command(
                command, operation="ke federated-discover", execution_budget=execution_budget
            )
        except FileNotFoundError as exc:
            raise KeCommandError(
                f"Could not run {ke_executable!r} -- "
                "is knowledge-engine-core installed and on PATH?"
            ) from exc

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise KeCommandError(f"`ke federated-discover` exited {result.returncode}: {message}")

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(
                f"`ke federated-discover` did not write a readable JSON output file: {exc}"
            ) from exc

    try:
        return parse_federated_discovery_result(payload)
    except FederatedDiscoveryParseError as exc:
        raise KeCommandError(str(exc)) from exc


class FederatedDiscoverHistoryParseError(RuntimeError):
    """`ke federated-discover-history --output`'s JSON did not match the expected shape."""


@dataclasses.dataclass(frozen=True)
class SearchCoverageReport:
    """One persisted federated-discover run's public coverage facts.

    Mirrors Core's ``SearchCoverageReport.to_dict()``
    (`knowledge_engine/federated_search_ledger.py`) field for field -- the
    same deterministic, provenance-safe shape ``federated-coverage-report``
    and `federated-discover --output`'s own ``coverage`` field already
    expose. ``initiated_by``, ``project_id``, and ``research_question_id``
    are internal run context and deliberately never appear here, matching
    Core's own docstring for this type.
    """

    search_run_id: str
    created_at: str
    query_text: str
    year_from: int | None
    year_to: int | None
    limit_per_provider: int
    completeness: str
    candidate_count: int
    providers_requested: tuple[str, ...]
    providers_attempted: tuple[str, ...]
    providers_completed: tuple[str, ...]
    providers_failed: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class FederatedDiscoverHistoryResult:
    """One `ke federated-discover-history --output` response, fully parsed and typed."""

    research_question_id: str
    run_count: int
    runs: tuple[SearchCoverageReport, ...]


def _parse_search_coverage_report(payload: dict[str, Any]) -> SearchCoverageReport:
    try:
        return SearchCoverageReport(
            search_run_id=payload["search_run_id"],
            created_at=payload["created_at"],
            query_text=payload["query_text"],
            year_from=payload.get("year_from"),
            year_to=payload.get("year_to"),
            limit_per_provider=payload["limit_per_provider"],
            completeness=payload["completeness"],
            candidate_count=payload["candidate_count"],
            providers_requested=tuple(payload["providers_requested"]),
            providers_attempted=tuple(payload["providers_attempted"]),
            providers_completed=tuple(payload["providers_completed"]),
            providers_failed=tuple(payload["providers_failed"]),
        )
    except (KeyError, TypeError) as exc:
        raise FederatedDiscoverHistoryParseError(
            f"`ke federated-discover-history --output` payload has a malformed run record: {exc}"
        ) from exc


def parse_federated_discover_history_result(
    payload: dict[str, Any],
) -> FederatedDiscoverHistoryResult:
    """Parse Core's `federated-discover-history --output` snapshot without guessing.

    A `research_question_id` with no recorded runs is an expected, honest
    state (Core's own command docstring: "a tracked question with no prior
    recorded search is an expected, honest state"), not an error --
    ``run_count`` is simply ``0`` and ``runs`` is empty.
    """

    try:
        research_question_id = payload["research_question_id"]
        run_count = payload["run_count"]
        raw_runs = payload["runs"]
    except (KeyError, TypeError) as exc:
        raise FederatedDiscoverHistoryParseError(
            f"`ke federated-discover-history --output` payload is missing a required field: {exc}"
        ) from exc

    if not isinstance(raw_runs, list):
        raise FederatedDiscoverHistoryParseError(
            "`ke federated-discover-history --output` payload's `runs` field is not a list."
        )

    runs = tuple(_parse_search_coverage_report(run) for run in raw_runs)

    return FederatedDiscoverHistoryResult(
        research_question_id=research_question_id,
        run_count=run_count,
        runs=runs,
    )


def federated_discover_history(
    research_question_id: str,
    *,
    ledger_root: Path,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> FederatedDiscoverHistoryResult:
    """Run `ke federated-discover-history <id> --output <tmp>` and return the parsed result.

    The `ke_client` wrapper for Core's FRD-6 follow-up history command --
    the first ledger read that discovers which `federated-discover` runs
    exist for a tracked `research_question_id` at all (see
    `docs/core_interface_contract.md`). This is the capability
    `knowledge-engine-web`'s WEB-FRD-5 freshness-history design
    (`docs/roadmap/web_frd5_freshness_history_design.md`, section 5, items
    3-4) named as blocking: until this wrapper existed, no run for a
    tracked question was reachable from Web through the sanctioned
    `ke_client` boundary at all, even a single one.

    Like `federated_discover` above, structured output is written to
    `--output <path>` rather than stdout; this wrapper writes that
    snapshot to a private temporary file, parses it, and discards the
    file -- the caller only sees the typed result. Deliberately just the
    subprocess/parse boundary: nothing here decides what "changed" between
    two runs, diffs them, or renders anything -- that comparison remains a
    future Web-side concern per the design document's own division of
    labor (Core/AI supply facts, Web renders a diff over facts it does not
    invent). Raises `KeCommandError` on command or contract failure and
    never returns a partial or guessed result. An empty `runs` tuple is a
    valid, non-error result: Core reports a tracked question with no prior
    recorded search plainly, never as a failure.
    """

    with tempfile.TemporaryDirectory(prefix="ke-federated-discover-history-") as scratch_dir:
        output_path = Path(scratch_dir) / "result.json"
        command = [
            _resolve_ke_executable(ke_executable),
            "federated-discover-history",
            research_question_id,
            "--ledger-root",
            str(ledger_root),
            "--output",
            str(output_path),
        ]

        try:
            result = _run_ke_command(
                command,
                operation="ke federated-discover-history",
                execution_budget=execution_budget,
            )
        except FileNotFoundError as exc:
            raise KeCommandError(
                f"Could not run {ke_executable!r} -- "
                "is knowledge-engine-core installed and on PATH?"
            ) from exc

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise KeCommandError(
                f"`ke federated-discover-history` exited {result.returncode}: {message}"
            )

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(
                f"`ke federated-discover-history` did not write a readable JSON output file: {exc}"
            ) from exc

    try:
        return parse_federated_discover_history_result(payload)
    except FederatedDiscoverHistoryParseError as exc:
        raise KeCommandError(str(exc)) from exc


class FederatedCoverageReportParseError(RuntimeError):
    """`ke federated-coverage-report --output`'s JSON did not match the expected shape."""


@dataclasses.dataclass(frozen=True)
class FederatedCandidateObservation:
    """One provider's full persisted observation of one candidate, for one past run.

    Mirrors Core's `CandidateObservationRecord.to_dict()`
    (`knowledge_engine/federated_search_ledger.py`) field for field -- the
    durable, per-provider observation `federated-coverage-report --output`
    now exposes for one specific past run by ID. This is a richer shape than
    `FederatedProviderObservationFlags` above: that type is
    `federated_discover`'s at-request-time subset (only the
    publication-status and preprint flags); this type is every field
    Core persisted for the observation. AI does not merge, vote on, or pick
    an authoritative provider value across observations.
    """

    provider: str
    provider_id: str
    title: str
    authors: tuple[str, ...]
    publication_year: int | None
    venue: str | None
    abstract: str | None
    doi: str | None
    pmid: str | None
    pmcid: str | None
    arxiv_id: str | None
    openalex_id: str | None
    semantic_scholar_id: str | None
    landing_url: str | None
    full_text_url: str | None
    xml_url: str | None
    license: str | None
    metadata_source: str | None
    pmcid_source: str | None
    open_access_source: str | None
    citation_count: int | None
    open_access: bool | None
    retracted: bool | None
    preprint: bool | None
    preprint_version: int | None
    related_journal_doi: str | None
    related_journal_reference: str | None
    retrieved_at: str | None
    corrected: bool | None = None
    expression_of_concern: bool | None = None
    withdrawn: bool | None = None


@dataclasses.dataclass(frozen=True)
class FederatedCandidateRecord:
    """One persisted deduplicated candidate for a specific past federated-discover run.

    Mirrors Core's `CandidateRecord.to_dict()` field for field.
    ``canonical_id`` is Core-owned work identity; AI does not re-deduplicate
    candidates or select an authoritative provider observation. A run
    persisted before Core's candidate-snapshot follow-up landed has no
    candidates recorded -- Core reports that as an honest empty list, never
    a fabricated or reconstructed one, and this type is unchanged either way.
    """

    canonical_id: str
    title: str
    observations: tuple[FederatedCandidateObservation, ...]
    doi: str | None
    publication_year: int | None


@dataclasses.dataclass(frozen=True)
class FederatedCoverageReportResult:
    """One `ke federated-coverage-report --output` response, fully parsed and typed.

    Pairs one past run's public `SearchCoverageReport` with that same run's
    full deduplicated candidate snapshot -- the point-lookup capability
    `docs/roadmap/federated_discovery_orchestration_adoption.md` named as
    deliberately deferred until Core added an `--output` option to
    `federated-coverage-report`.
    """

    search_run_id: str
    coverage: SearchCoverageReport
    candidates: tuple[FederatedCandidateRecord, ...]


def _parse_federated_candidate_observation(
    payload: dict[str, Any],
) -> FederatedCandidateObservation:
    try:
        return FederatedCandidateObservation(
            provider=payload["provider"],
            provider_id=payload["provider_id"],
            title=payload["title"],
            authors=tuple(payload.get("authors") or ()),
            publication_year=payload.get("publication_year"),
            venue=payload.get("venue"),
            abstract=payload.get("abstract"),
            doi=payload.get("doi"),
            pmid=payload.get("pmid"),
            pmcid=payload.get("pmcid"),
            arxiv_id=payload.get("arxiv_id"),
            openalex_id=payload.get("openalex_id"),
            semantic_scholar_id=payload.get("semantic_scholar_id"),
            landing_url=payload.get("landing_url"),
            full_text_url=payload.get("full_text_url"),
            xml_url=payload.get("xml_url"),
            license=payload.get("license"),
            metadata_source=payload.get("metadata_source"),
            pmcid_source=payload.get("pmcid_source"),
            open_access_source=payload.get("open_access_source"),
            citation_count=payload.get("citation_count"),
            open_access=payload.get("open_access"),
            retracted=payload.get("retracted"),
            preprint=payload.get("preprint"),
            preprint_version=payload.get("preprint_version"),
            related_journal_doi=payload.get("related_journal_doi"),
            related_journal_reference=payload.get("related_journal_reference"),
            retrieved_at=payload.get("retrieved_at"),
            corrected=payload.get("corrected"),
            expression_of_concern=payload.get("expression_of_concern"),
            withdrawn=payload.get("withdrawn"),
        )
    except (KeyError, TypeError) as exc:
        raise FederatedCoverageReportParseError(
            "`ke federated-coverage-report --output` payload has a malformed "
            f"candidate observation: {exc}"
        ) from exc


def _parse_federated_candidate_record(payload: dict[str, Any]) -> FederatedCandidateRecord:
    try:
        canonical_id = payload["canonical_id"]
        title = payload["title"]
        raw_observations = payload["observations"]
    except (KeyError, TypeError) as exc:
        raise FederatedCoverageReportParseError(
            f"`ke federated-coverage-report --output` payload has a malformed candidate: {exc}"
        ) from exc

    if not isinstance(raw_observations, list):
        raise FederatedCoverageReportParseError(
            "`ke federated-coverage-report --output` payload's candidate "
            "`observations` field is not a list."
        )

    return FederatedCandidateRecord(
        canonical_id=canonical_id,
        title=title,
        observations=tuple(
            _parse_federated_candidate_observation(observation) for observation in raw_observations
        ),
        doi=payload.get("doi"),
        publication_year=payload.get("publication_year"),
    )


def parse_federated_coverage_report_result(
    payload: dict[str, Any],
) -> FederatedCoverageReportResult:
    """Parse Core's `federated-coverage-report --output` snapshot without guessing.

    A run persisted before Core's candidate-snapshot follow-up existed
    carries an empty `candidates` list -- Core's own documented, honest
    "not recorded" state, not an error here either.
    """

    try:
        search_run_id = payload["search_run_id"]
        raw_coverage = payload["coverage"]
        raw_candidates = payload["candidates"]
    except (KeyError, TypeError) as exc:
        raise FederatedCoverageReportParseError(
            f"`ke federated-coverage-report --output` payload is missing a required field: {exc}"
        ) from exc

    if not isinstance(raw_coverage, dict):
        raise FederatedCoverageReportParseError(
            "`ke federated-coverage-report --output` payload's `coverage` field is not an object."
        )
    if not isinstance(raw_candidates, list):
        raise FederatedCoverageReportParseError(
            "`ke federated-coverage-report --output` payload's `candidates` field is not a list."
        )

    try:
        coverage = _parse_search_coverage_report(raw_coverage)
    except FederatedDiscoverHistoryParseError as exc:
        raise FederatedCoverageReportParseError(
            "`ke federated-coverage-report --output` payload has a malformed "
            f"coverage record: {exc}"
        ) from exc

    candidates = tuple(_parse_federated_candidate_record(candidate) for candidate in raw_candidates)

    return FederatedCoverageReportResult(
        search_run_id=search_run_id,
        coverage=coverage,
        candidates=candidates,
    )


def federated_coverage_report(
    search_run_id: str,
    *,
    ledger_root: Path,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> FederatedCoverageReportResult:
    """Run `ke federated-coverage-report <id> --ledger-root <dir> --output <tmp>`.

    The `ke_client` wrapper for Core's FRD-6 candidate-snapshot follow-up
    (`docs/core_interface_contract.md`): a point lookup of one specific past
    federated-discover run's public coverage facts plus its full
    deduplicated candidate snapshot (title, DOI, publication year, and every
    provider's full observation), now durable in Core's
    `FederatedSearchLedger` and re-fetchable by `search_run_id` without
    rerunning the search. This is the point-lookup wrapper
    `docs/roadmap/federated_discovery_orchestration_adoption.md` recorded as
    deliberately deferred until Core added an `--output` option to this
    command -- it now has one.

    Like `federated_discover`/`federated_discover_history` above,
    structured output is written to `--output <path>` rather than stdout;
    this wrapper writes that snapshot to a private temporary file, parses
    it, and discards the file -- the caller only sees the typed result.
    Deliberately just the subprocess/parse boundary: nothing here decides
    what "changed" between two runs or renders anything -- that remains a
    future Web-side concern. Raises `KeCommandError` on command or contract
    failure and never returns a partial or guessed result. A run recorded
    before Core's candidate-snapshot follow-up existed returns an honest
    empty `candidates` tuple, never a fabricated one.
    """

    with tempfile.TemporaryDirectory(prefix="ke-federated-coverage-report-") as scratch_dir:
        output_path = Path(scratch_dir) / "result.json"
        command = [
            _resolve_ke_executable(ke_executable),
            "federated-coverage-report",
            search_run_id,
            "--ledger-root",
            str(ledger_root),
            "--output",
            str(output_path),
        ]

        try:
            result = _run_ke_command(
                command,
                operation="ke federated-coverage-report",
                execution_budget=execution_budget,
            )
        except FileNotFoundError as exc:
            raise KeCommandError(
                f"Could not run {ke_executable!r} -- "
                "is knowledge-engine-core installed and on PATH?"
            ) from exc

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise KeCommandError(
                f"`ke federated-coverage-report` exited {result.returncode}: {message}"
            )

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(
                f"`ke federated-coverage-report` did not write a readable JSON output file: {exc}"
            ) from exc

    try:
        return parse_federated_coverage_report_result(payload)
    except FederatedCoverageReportParseError as exc:
        raise KeCommandError(str(exc)) from exc


class CitationSnowballParseError(RuntimeError):
    """`ke citation-snowball --output`'s JSON did not match the expected shape."""


@dataclasses.dataclass(frozen=True)
class CitationSnowballCandidate:
    """One Core-discovered citation-snowball candidate for downstream display.

    Mirrors ``FederatedCandidateSummary`` -- ``canonical_id`` is Core-owned
    work identity, ``providers``/``observation_flags`` are provider-native
    assertions this project does not merge or vote on.
    """

    canonical_id: str
    title: str
    doi: str | None
    publication_year: int | None
    providers: tuple[str, ...]
    observation_flags: tuple[FederatedProviderObservationFlags, ...] = ()


@dataclasses.dataclass(frozen=True)
class CitationSnowballEdge:
    """One provider-asserted provenance edge explaining why a candidate was found."""

    provider: str
    seed_identifier: str
    related_provider_id: str
    direction: str
    retrieved_at: str


@dataclasses.dataclass(frozen=True)
class CitationSnowballResult:
    """One `ke citation-snowball --output` response, fully parsed and typed."""

    snowball_run_id: str
    provider: str
    seed_identifiers: tuple[str, ...]
    directions: tuple[str, ...]
    max_depth: int
    limit_per_traversal: int
    max_candidates: int
    completeness: str
    truncated: bool
    candidates: tuple[CitationSnowballCandidate, ...]
    edges: tuple[CitationSnowballEdge, ...]


def parse_citation_snowball_result(payload: dict[str, Any]) -> CitationSnowballResult:
    """Parse Core's citation-snowball `--output` snapshot without guessing omitted facts.

    Each candidate's per-provider `retracted`/`corrected`/
    `expression_of_concern`/`withdrawn`/`preprint`/`preprint_version`
    observations are preserved as `observation_flags`, the same
    "absent is not negative" contract `parse_federated_discovery_result`
    uses -- a provider observation that omits these fields parses to
    explicit `None` rather than a guessed `False`.
    """

    try:
        snowball_run_id = payload["snowball_run_id"]
        provider = payload["provider"]
        plan = payload["plan"]
        seed_identifiers = plan["seed_identifiers"]
        directions = plan["directions"]
        max_depth = plan["max_depth"]
        limit_per_traversal = plan["limit_per_traversal"]
        max_candidates = plan["max_candidates"]
        completeness = payload["completeness"]
        truncated = payload["truncated"]
        raw_candidates = payload["candidates"]
        raw_edges = payload["edges"]
    except (KeyError, TypeError) as exc:
        raise CitationSnowballParseError(
            f"`ke citation-snowball --output` payload is missing a required field: {exc}"
        ) from exc

    try:
        candidates = tuple(
            CitationSnowballCandidate(
                canonical_id=candidate["canonical_id"],
                title=candidate["title"],
                doi=candidate.get("doi"),
                publication_year=candidate.get("publication_year"),
                providers=tuple(
                    sorted({observation["provider"] for observation in candidate["observations"]})
                ),
                observation_flags=tuple(
                    FederatedProviderObservationFlags(
                        provider=observation["provider"],
                        retracted=observation.get("retracted"),
                        preprint=observation.get("preprint"),
                        preprint_version=observation.get("preprint_version"),
                        corrected=observation.get("corrected"),
                        expression_of_concern=observation.get("expression_of_concern"),
                        withdrawn=observation.get("withdrawn"),
                    )
                    for observation in candidate["observations"]
                ),
            )
            for candidate in raw_candidates
        )
        edges = tuple(
            CitationSnowballEdge(
                provider=edge["provider"],
                seed_identifier=edge["seed_identifier"],
                related_provider_id=edge["related_provider_id"],
                direction=edge["direction"],
                retrieved_at=edge["retrieved_at"],
            )
            for edge in raw_edges
        )
    except (KeyError, TypeError) as exc:
        raise CitationSnowballParseError(
            f"`ke citation-snowball --output` payload is malformed: {exc}"
        ) from exc

    return CitationSnowballResult(
        snowball_run_id=snowball_run_id,
        provider=provider,
        seed_identifiers=tuple(seed_identifiers),
        directions=tuple(directions),
        max_depth=max_depth,
        limit_per_traversal=limit_per_traversal,
        max_candidates=max_candidates,
        completeness=completeness,
        truncated=truncated,
        candidates=candidates,
        edges=edges,
    )


def citation_snowball(
    seed_identifiers: tuple[str, ...],
    *,
    ledger_root: Path,
    provider: str = "semantic_scholar",
    directions: tuple[str, ...] = ("references", "citations"),
    max_depth: int = 1,
    limit_per_traversal: int = 25,
    max_candidates: int = 100,
    openalex_api_key: str | None = None,
    semantic_scholar_api_key: str | None = None,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> CitationSnowballResult:
    """Run `ke citation-snowball --output <tmp>` and return the parsed result.

    The first `ke_client` wrapper for Core's FRD-7 citation-snowball
    command (AI-FRD-4's named prerequisite -- see
    `docs/roadmap/federated_discovery_orchestration_adoption.md`). Like
    `federated_discover` above, structured output is written to
    `--output <path>` rather than stdout; this wrapper writes that
    snapshot to a private temporary file, parses it, and discards the
    file -- the caller only sees the typed result. Deliberately just the
    subprocess/parse boundary: nothing here decides *when* a Research
    Session should run a citation snowball, selects seeds, or wires this
    into `run_research_question`'s own planning -- that policy remains
    AI-FRD-4's own next continuation, the same way AI-FRD-3's compiler
    exists without being called from planning yet. Raises `KeCommandError`
    on command or contract failure and never returns a partial or guessed
    result.
    """

    with tempfile.TemporaryDirectory(prefix="ke-citation-snowball-") as scratch_dir:
        output_path = Path(scratch_dir) / "result.json"
        command = [
            _resolve_ke_executable(ke_executable),
            "citation-snowball",
            "--seeds",
            ",".join(seed_identifiers),
            "--ledger-root",
            str(ledger_root),
            "--provider",
            provider,
            "--directions",
            ",".join(directions),
            "--max-depth",
            str(max_depth),
            "--limit-per-traversal",
            str(limit_per_traversal),
            "--max-candidates",
            str(max_candidates),
            "--output",
            str(output_path),
        ]
        if openalex_api_key:
            command += ["--openalex-api-key", openalex_api_key]
        if semantic_scholar_api_key:
            command += ["--semantic-scholar-api-key", semantic_scholar_api_key]

        try:
            result = _run_ke_command(
                command, operation="ke citation-snowball", execution_budget=execution_budget
            )
        except FileNotFoundError as exc:
            raise KeCommandError(
                f"Could not run {ke_executable!r} -- "
                "is knowledge-engine-core installed and on PATH?"
            ) from exc

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise KeCommandError(f"`ke citation-snowball` exited {result.returncode}: {message}")

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(
                f"`ke citation-snowball` did not write a readable JSON output file: {exc}"
            ) from exc

    try:
        return parse_citation_snowball_result(payload)
    except CitationSnowballParseError as exc:
        raise KeCommandError(str(exc)) from exc


class GeneralQuestionAcquisitionParseError(RuntimeError):
    """`ke general-question-acquisition-plan --output`'s JSON did not match the expected shape."""


@dataclasses.dataclass(frozen=True)
class GeneralQuestionAcquisitionIdentity:
    """Provider-neutral identity facts Core preserved from the search snapshot."""

    canonical_id: str
    doi: str | None
    pmid: str | None
    pmcid: str | None
    arxiv_id: str | None
    openalex_id: str | None
    semantic_scholar_id: str | None


@dataclasses.dataclass(frozen=True)
class GeneralQuestionAcquisitionItem:
    """One Core-resolved candidate-selection result for a bounded acquisition plan.

    ``disposition`` is one of Core's stable values (``already_indexed``,
    ``eligible_full_text``, ``metadata_only``, ``skipped_budget``,
    ``not_found_in_run``) -- acquisition eligibility, never scientific
    support. AI does not reinterpret or re-rank this value.
    """

    candidate_id: str
    title: str | None
    disposition: str
    identity: GeneralQuestionAcquisitionIdentity | None
    selected_observation_provider: str | None
    full_text_url: str | None
    xml_url: str | None
    license: str | None
    open_access: bool | None
    existing_paper_id: int | None
    reason: str | None


@dataclasses.dataclass(frozen=True)
class GeneralQuestionAcquisitionPlanResult:
    """One `ke general-question-acquisition-plan --output` response, fully parsed and typed.

    Mirrors Core's ``GeneralQuestionAcquisitionPlan.to_dict()``
    (`knowledge_engine/general_question_acquisition.py`) field for field. This
    plans and reuses candidate resolution only -- it never implies a source
    was downloaded, parsed, or promoted to an Evidence Record (Core's own
    CORE-GQR-3/GQR-4 remain future work for that).
    """

    schema_version: int
    search_run_id: str
    research_question_id: str
    query_text: str
    requested_candidate_count: int
    resolved_candidate_count: int
    already_indexed_count: int
    full_text_selected_count: int
    metadata_only_count: int
    skipped_budget_count: int
    missing_candidate_count: int
    provider_failures: tuple[str, ...]
    items: tuple[GeneralQuestionAcquisitionItem, ...]


def _parse_general_question_acquisition_identity(
    payload: dict[str, Any] | None,
) -> GeneralQuestionAcquisitionIdentity | None:
    if payload is None:
        return None
    try:
        return GeneralQuestionAcquisitionIdentity(
            canonical_id=payload["canonical_id"],
            doi=payload.get("doi"),
            pmid=payload.get("pmid"),
            pmcid=payload.get("pmcid"),
            arxiv_id=payload.get("arxiv_id"),
            openalex_id=payload.get("openalex_id"),
            semantic_scholar_id=payload.get("semantic_scholar_id"),
        )
    except (KeyError, TypeError) as exc:
        raise GeneralQuestionAcquisitionParseError(
            "`ke general-question-acquisition-plan --output` payload has a malformed "
            f"candidate identity: {exc}"
        ) from exc


def _parse_general_question_acquisition_item(
    payload: dict[str, Any],
) -> GeneralQuestionAcquisitionItem:
    try:
        return GeneralQuestionAcquisitionItem(
            candidate_id=payload["candidate_id"],
            title=payload.get("title"),
            disposition=payload["disposition"],
            identity=_parse_general_question_acquisition_identity(payload.get("identity")),
            selected_observation_provider=payload.get("selected_observation_provider"),
            full_text_url=payload.get("full_text_url"),
            xml_url=payload.get("xml_url"),
            license=payload.get("license"),
            open_access=payload.get("open_access"),
            existing_paper_id=payload.get("existing_paper_id"),
            reason=payload.get("reason"),
        )
    except (KeyError, TypeError) as exc:
        raise GeneralQuestionAcquisitionParseError(
            f"`ke general-question-acquisition-plan --output` payload has a malformed item: {exc}"
        ) from exc


def parse_general_question_acquisition_plan_result(
    payload: dict[str, Any],
) -> GeneralQuestionAcquisitionPlanResult:
    """Parse Core's `general-question-acquisition-plan --output` snapshot without guessing.

    Every field this parses is required in Core's own
    ``GeneralQuestionAcquisitionPlan.to_dict()`` output -- a missing field
    raises rather than defaulting, the same strictness
    ``parse_federated_discovery_result`` applies to its own required fields.
    """

    try:
        schema_version = payload["schema_version"]
        search_run_id = payload["search_run_id"]
        research_question_id = payload["research_question_id"]
        query_text = payload["query_text"]
        requested_candidate_count = payload["requested_candidate_count"]
        resolved_candidate_count = payload["resolved_candidate_count"]
        already_indexed_count = payload["already_indexed_count"]
        full_text_selected_count = payload["full_text_selected_count"]
        metadata_only_count = payload["metadata_only_count"]
        skipped_budget_count = payload["skipped_budget_count"]
        missing_candidate_count = payload["missing_candidate_count"]
        provider_failures = payload["provider_failures"]
        raw_items = payload["items"]
    except (KeyError, TypeError) as exc:
        raise GeneralQuestionAcquisitionParseError(
            "`ke general-question-acquisition-plan --output` payload is missing a required "
            f"field: {exc}"
        ) from exc

    if not isinstance(raw_items, list):
        raise GeneralQuestionAcquisitionParseError(
            "`ke general-question-acquisition-plan --output` payload's `items` field is not a list."
        )

    items = tuple(_parse_general_question_acquisition_item(item) for item in raw_items)

    return GeneralQuestionAcquisitionPlanResult(
        schema_version=schema_version,
        search_run_id=search_run_id,
        research_question_id=research_question_id,
        query_text=query_text,
        requested_candidate_count=requested_candidate_count,
        resolved_candidate_count=resolved_candidate_count,
        already_indexed_count=already_indexed_count,
        full_text_selected_count=full_text_selected_count,
        metadata_only_count=metadata_only_count,
        skipped_budget_count=skipped_budget_count,
        missing_candidate_count=missing_candidate_count,
        provider_failures=tuple(provider_failures),
        items=items,
    )


def general_question_acquisition_plan(
    *,
    search_run_id: str,
    research_question_id: str,
    candidate_ids: tuple[str, ...],
    ledger_root: Path,
    max_candidates: int = 10,
    max_full_text_acquisitions: int = 5,
    max_elapsed_seconds: int = 120,
    allow_metadata_only: bool = True,
    no_database: bool = False,
    ke_executable: str = "ke",
    execution_budget: ExecutionBudget | None = None,
) -> GeneralQuestionAcquisitionPlanResult:
    """Run `ke general-question-acquisition-plan --output <tmp>` and return the parsed result.

    The first `ke_client` wrapper for Core's CORE-GQR-1/GQR-2 acquisition-plan
    command (`docs/general_question_research_loop_v1.md`,
    `docs/core_interface_contract.md`) -- the reachable path
    `knowledge-engine-ai` issue #69's Stage 4 (candidate triage and
    acquisition) names as its bridge into Core. Unlike the other commands
    wrapped in this module, Core's command takes its request as a JSON
    *file* argument (``GeneralQuestionAcquisitionRequest.from_json``), not
    flags -- this wrapper writes that request to a private temporary file
    alongside the usual ``--output`` snapshot file, runs the command, parses
    the result, and discards both files; the caller only sees the typed
    result.

    Every returned item's ``disposition`` describes acquisition eligibility
    only -- ``eligible_full_text`` never means a source was actually
    acquired, parsed, or promoted to an Evidence Record. Core's own
    CORE-GQR-3 (acquisition routing) and CORE-GQR-4 (persist and parse)
    remain future work; this wrapper only reaches the planning command that
    already exists today. Deliberately just the subprocess/parse boundary,
    the same division `citation_snowball` and `federated_discover` use:
    nothing here decides *when* to request a plan, selects candidate IDs, or
    wires this into `run_research_question`'s own orchestration -- that
    remains future work for issue #69.

    ``no_database=True`` forwards Core's ``--no-database`` flag, skipping the
    already-indexed lookup against the local corpus and reporting every
    resolved candidate purely against the search-run snapshot. Raises
    `KeCommandError` on command or contract failure and never returns a
    partial or guessed result.
    """

    request_payload: dict[str, Any] = {
        "schema_version": 1,
        "search_run_id": search_run_id,
        "research_question_id": research_question_id,
        "candidate_ids": list(candidate_ids),
        "max_candidates": max_candidates,
        "max_full_text_acquisitions": max_full_text_acquisitions,
        "max_elapsed_seconds": max_elapsed_seconds,
        "allow_metadata_only": allow_metadata_only,
    }

    with tempfile.TemporaryDirectory(prefix="ke-general-question-acquisition-plan-") as scratch_dir:
        request_path = Path(scratch_dir) / "request.json"
        output_path = Path(scratch_dir) / "result.json"
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")

        command = [
            _resolve_ke_executable(ke_executable),
            "general-question-acquisition-plan",
            str(request_path),
            "--ledger-root",
            str(ledger_root),
            "--output",
            str(output_path),
        ]
        if no_database:
            command.append("--no-database")

        try:
            result = _run_ke_command(
                command,
                operation="ke general-question-acquisition-plan",
                execution_budget=execution_budget,
            )
        except FileNotFoundError as exc:
            raise KeCommandError(
                f"Could not run {ke_executable!r} -- "
                "is knowledge-engine-core installed and on PATH?"
            ) from exc

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise KeCommandError(
                f"`ke general-question-acquisition-plan` exited {result.returncode}: {message}"
            )

        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeCommandError(
                "`ke general-question-acquisition-plan` did not write a readable JSON output "
                f"file: {exc}"
            ) from exc

    try:
        return parse_general_question_acquisition_plan_result(payload)
    except GeneralQuestionAcquisitionParseError as exc:
        raise KeCommandError(str(exc)) from exc
