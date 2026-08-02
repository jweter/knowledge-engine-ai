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
import subprocess
from pathlib import Path

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


def evidence_report(
    question: str,
    *,
    sources: Path,
    evidence: Path,
    limit: int = 5,
    ke_executable: str = "ke",
) -> EvidenceReport:
    """Run `ke evidence-report <question> --format json` and return the parsed result.

    Raises `KeCommandError` if `ke` exits non-zero (e.g. no relevant
    papers found in the indexed corpus, or `ke` is not installed) or
    produces output that does not parse as the documented JSON contract
    -- never returns a partial or guessed result.
    """

    command = [
        ke_executable,
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
        result = subprocess.run(command, capture_output=True, text=True, check=False)
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
        ke_executable,
        "evidence-intelligence",
        "--evidence",
        str(evidence),
        "--evidence-record-id",
        evidence_record_id,
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
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


def enriched_evidence_report(
    question: str,
    *,
    sources: Path,
    evidence: Path,
    limit: int = 5,
    ke_executable: str = "ke",
) -> EvidenceReport:
    """Run `evidence_report`, then attach each matched record's Evidence Intelligence.

    Still retrieval plus already-computed, already-stored signals only --
    no synthesis, no new judgment. Each `EvidenceRecord` with an
    `evidence_record_id` gets one `evidence_intelligence` lookup; records
    without a graph claim yet simply carry `evidence_intelligence=None`
    (see `evidence_intelligence`'s own docstring), not an error.
    """

    report = evidence_report(
        question, sources=sources, evidence=evidence, limit=limit, ke_executable=ke_executable
    )

    enriched_papers = []
    for paper in report.papers:
        enriched_records = []
        for record in paper.evidence_records:
            intelligence = None
            if record.evidence_record_id:
                intelligence = evidence_intelligence(
                    record.evidence_record_id, evidence=evidence, ke_executable=ke_executable
                )
            enriched_records.append(dataclasses.replace(record, evidence_intelligence=intelligence))
        enriched_papers.append(dataclasses.replace(paper, evidence_records=enriched_records))

    return dataclasses.replace(report, papers=enriched_papers)
