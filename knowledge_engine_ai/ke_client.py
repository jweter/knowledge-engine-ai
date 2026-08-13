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
from pathlib import Path

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
) -> subprocess.CompletedProcess[str]:
    """Run one core command inside the shared wall-clock budget."""

    try:
        timeout = execution_budget.remaining_seconds() if execution_budget is not None else None
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
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
) -> EvidenceReport:
    """Run `ke evidence-report <question> --format json` and return the parsed result.

    Raises `KeCommandError` if `ke` exits non-zero (e.g. no relevant
    papers found in the indexed corpus, or `ke` is not installed) or
    produces output that does not parse as the documented JSON contract
    -- never returns a partial or guessed result.
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
            command, operation="ke evidence-report", execution_budget=execution_budget
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
