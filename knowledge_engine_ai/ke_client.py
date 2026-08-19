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
    """One provider's retraction/preprint observation for one candidate.

    These are provider-native assertions, preserved per-provider like
    ``FederatedProviderAssertion`` above -- AI does not merge, vote on, or
    pick an authoritative value across providers. ``None`` means the
    provider did not report the flag, which is distinct from the provider
    reporting ``False``.
    """

    provider: str
    retracted: bool | None
    preprint: bool | None
    preprint_version: int | None


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

    Each candidate's per-provider ``retracted``/``preprint``/``preprint_version``
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

    Each candidate's per-provider `retracted`/`preprint`/`preprint_version`
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
