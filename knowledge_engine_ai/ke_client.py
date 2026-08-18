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
class FederatedCandidateSummary:
    """One deduplicated federated discovery candidate, display fields only.

    Deliberately narrower than core's full `FederatedCandidate` contract
    (no per-observation abstract/authors/venue) -- this is the first,
    minimal slice `knowledge-engine-web` needs to render a provider
    coverage view (`docs/federated_discovery_transparency_roadmap.md`'s
    WEB-FRD-1), not a full mirror of core's discovery contract. Widen this
    if a consumer needs more.
    """

    title: str
    doi: str | None
    publication_year: int | None
    providers: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class FederatedDiscoveryResult:
    """One `ke federated-discover --output` response, fully parsed and typed."""

    search_run_id: str
    query_text: str
    completeness: str
    provider_statuses: tuple[FederatedProviderStatus, ...]
    candidates: tuple[FederatedCandidateSummary, ...]


def parse_federated_discovery_result(payload: dict[str, Any]) -> FederatedDiscoveryResult:
    """Parse `ke federated-discover --output`'s JSON into `FederatedDiscoveryResult`.

    Raises `FederatedDiscoveryParseError` on a missing required field --
    never guesses a default for data `core` did not actually provide.
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
                title=candidate["title"],
                doi=candidate.get("doi"),
                publication_year=candidate.get("publication_year"),
                providers=tuple(
                    sorted({observation["provider"] for observation in candidate["observations"]})
                ),
            )
            for candidate in raw_candidates
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
    )


def federated_discover(
    query: str,
    *,
    ledger_root: Path,
    limit: int = 20,
    providers: tuple[str, ...] | None = None,
    openalex_api_key: str | None = None,
    semantic_scholar_api_key: str | None = None,
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
