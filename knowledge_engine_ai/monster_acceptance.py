"""Unattended local Monster #79 acceptance bridge.

This module joins three existing authorities into one fail-closed verdict:

- :class:`~knowledge_engine_ai.unattended_acceptance.UnattendedAcceptanceManifest`
  binds exact AI/Core/Web SHAs, the Core worker request, and the local Ollama
  runtime/model;
- the Research Report v1 build artifact
  (:meth:`ResearchReportBuildResult.to_dict`) produced by the normal research
  session path; and
- the golden research-case contract in
  :mod:`knowledge_engine_ai.research_case_benchmark`, scored only from a
  structured :class:`ResearchCaseRunSnapshot` artifact.

It does not run research, call a model, or derive benchmark facts from narrative
prose. Missing, unresolved, or unknown evidence never becomes ``PASS``. The
emitted verdict contains only sanitized derived facts: identities, reason codes,
guard names, public seed identifiers, and a digest of the report artifact. It
never copies report prose, source documents, worker summaries, or local paths.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

import typer

from knowledge_engine_ai.copilot.research_report import RESEARCH_REPORT_SCHEMA_VERSION
from knowledge_engine_ai.copilot.research_state import ResearchState
from knowledge_engine_ai.research_case_benchmark import (
    GoldenResearchCase,
    ResearchCaseBenchmarkResult,
    ResearchCaseRunSnapshot,
    SourceFieldGap,
    default_golden_research_cases,
    evaluate_research_case,
)
from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

MONSTER_CASE_ID = "monster-energy-bp-one-year"
MONSTER_ACCEPTANCE_SCHEMA_VERSION = 1

# Research states in which the session produced no answer to accept.
_NON_ANSWER_RESEARCH_STATES = frozenset(
    {
        ResearchState.RESEARCH_REQUIRED.value,
        ResearchState.RESEARCHING.value,
        ResearchState.BLOCKED.value,
    }
)
_KNOWN_RESEARCH_STATES = frozenset(state.value for state in ResearchState)
_IDENTITY_FIELDS = ("ai_sha", "core_sha", "web_sha", "ollama_model", "ollama_runtime_id")
_SNAPSHOT_FIELDS = tuple(field.name for field in fields(ResearchCaseRunSnapshot))
_SNAPSHOT_TUPLE_FIELDS = frozenset(
    {
        "attempted_providers",
        "degraded_providers",
        "reported_degraded_providers",
        "covered_variants",
        "covered_dimensions",
        "completed_search_tracks",
        "reviewed_source_ids",
        "represented_counterevidence_source_ids",
        "source_fields_audited_source_ids",
        "violated_inference_guard_ids",
    }
)
_SNAPSHOT_INT_FIELDS = frozenset(
    {
        "initial_indexed_evidence_record_count",
        "factual_claim_count",
        "source_linked_factual_claim_count",
    }
)
_SNAPSHOT_BOOL_FIELDS = frozenset(
    {"discovery_triggered", "direct_long_term_study_found", "direct_long_term_gap_reported"}
)
_BENCHMARK_GUARD_FIELDS = tuple(
    field.name for field in fields(ResearchCaseBenchmarkResult) if field.name != "case_id"
)


class MonsterAcceptanceStatus(StrEnum):
    """Closed verdict vocabulary; only ``PASS`` is an acceptance pass."""

    PASS = "PASS"
    FAIL = "FAIL"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"


@dataclass(frozen=True)
class ObservedRuntimeIdentity:
    """Identity actually observed by the local runner at execution time."""

    ai_sha: str | None
    core_sha: str | None
    web_sha: str | None
    ollama_model: str | None
    ollama_runtime_id: str | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> ObservedRuntimeIdentity:
        source: Mapping[str, Any] = payload or {}
        values: dict[str, str | None] = {}
        for name in _IDENTITY_FIELDS:
            value = source.get(name)
            values[name] = value.strip() if isinstance(value, str) and value.strip() else None
        return cls(**values)


@dataclass(frozen=True)
class MonsterAcceptanceVerdict:
    """Sanitized, publishable result of one unattended Monster acceptance run."""

    status: MonsterAcceptanceStatus
    reasons: tuple[str, ...]
    case_id: str
    manifest: UnattendedAcceptanceManifest
    worker_status: str | None
    research_session_id: str | None
    research_state: str | None
    report_artifact_sha256: str | None
    benchmark: ResearchCaseBenchmarkResult | None

    @property
    def passed(self) -> bool:
        return self.status is MonsterAcceptanceStatus.PASS

    def to_dict(self) -> dict[str, object]:
        request = self.manifest.core_worker_request()
        return {
            "schema_version": MONSTER_ACCEPTANCE_SCHEMA_VERSION,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "case_id": self.case_id,
            "identity": {
                "ai_sha": self.manifest.ai_sha,
                "core_sha": self.manifest.core_sha,
                "web_sha": self.manifest.web_sha,
                "core_branch": self.manifest.core_branch,
                "environment_id": self.manifest.environment_id,
                "ollama_model": self.manifest.ollama_model,
                "ollama_runtime_id": self.manifest.ollama_runtime_id,
                "created_at_utc": self.manifest.created_at_utc,
                "manifest_identity_sha256": self.manifest.identity_sha256(),
                "core_request_id": request["request_id"],
            },
            "worker_status": self.worker_status,
            "research_session_id": self.research_session_id,
            "research_state": self.research_state,
            "report_artifact_sha256": self.report_artifact_sha256,
            "benchmark": _benchmark_payload(self.benchmark),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_monster_acceptance(
    manifest: UnattendedAcceptanceManifest,
    *,
    observed_identity: ObservedRuntimeIdentity,
    worker_result: Mapping[str, Any] | None,
    report_build: Mapping[str, Any] | None,
    benchmark_snapshot: Mapping[str, Any] | None,
    cases: tuple[GoldenResearchCase, ...] | None = None,
) -> MonsterAcceptanceVerdict:
    """Return a fail-closed Monster acceptance verdict for one unattended run.

    ``report_build`` is the ``ResearchReportBuildResult.to_dict()`` artifact.
    ``benchmark_snapshot`` carries every ``ResearchCaseRunSnapshot`` field plus
    the ``session_id`` of the research session it was observed from.
    """

    identity_reasons = _identity_reasons(manifest, observed_identity)
    environment_reasons: list[str] = []
    evidence_reasons: list[str] = []

    case = _golden_case(manifest.scenario_id, cases)
    if case is None:
        evidence_reasons.append("scenario_not_monster_golden_case")

    worker_status: str | None = None
    if worker_result is None:
        environment_reasons.append("worker_result_missing")
    else:
        try:
            worker_status = manifest.validate_worker_result(worker_result)
        except ValueError:
            environment_reasons.append("worker_result_invalid")
        else:
            if worker_status == "ENVIRONMENT_FAILURE":
                environment_reasons.append("worker_status_environment_failure")
            elif worker_status != "PASS":
                evidence_reasons.append(f"worker_status_{worker_status.lower()}")

    report, report_reasons = _report_payload(report_build)
    evidence_reasons.extend(report_reasons)
    report_digest = _canonical_sha256(report_build) if report_build is not None else None
    session_id = _nonblank(report.get("session_id")) if report is not None else None
    research_state = _nonblank(report.get("research_state")) if report is not None else None

    if report is not None and case is not None:
        evidence_reasons.extend(_report_contract_reasons(report, case))

    snapshot, snapshot_reasons = _snapshot_from_artifact(benchmark_snapshot)
    evidence_reasons.extend(snapshot_reasons)

    benchmark: ResearchCaseBenchmarkResult | None = None
    if snapshot is not None and report is not None:
        evidence_reasons.extend(_cross_artifact_reasons(benchmark_snapshot, snapshot, report))
    if snapshot is not None and case is not None:
        try:
            benchmark = evaluate_research_case(case, snapshot)
        except ValueError:
            evidence_reasons.append("benchmark_contract_violation")
        else:
            failed_guards = [
                f"benchmark_guard_failed:{name}"
                for name in _BENCHMARK_GUARD_FIELDS
                if getattr(benchmark, name)
            ]
            evidence_reasons.extend(failed_guards)
            if not benchmark.passes and not failed_guards:
                evidence_reasons.append("benchmark_failed")

    reasons = tuple(dict.fromkeys((*identity_reasons, *environment_reasons, *evidence_reasons)))
    if identity_reasons:
        status = MonsterAcceptanceStatus.FAIL
    elif environment_reasons:
        status = MonsterAcceptanceStatus.ENVIRONMENT_FAILURE
    elif reasons or benchmark is None or not benchmark.passes:
        status = MonsterAcceptanceStatus.FAIL
    else:
        status = MonsterAcceptanceStatus.PASS
    if status is not MonsterAcceptanceStatus.PASS and not reasons:
        reasons = ("benchmark_unavailable",)

    return MonsterAcceptanceVerdict(
        status=status,
        reasons=reasons,
        case_id=case.case_id if case is not None else MONSTER_CASE_ID,
        manifest=manifest,
        worker_status=worker_status,
        research_session_id=session_id,
        research_state=research_state if research_state in _KNOWN_RESEARCH_STATES else None,
        report_artifact_sha256=report_digest,
        benchmark=benchmark,
    )


def manifest_from_mapping(payload: Mapping[str, Any]) -> UnattendedAcceptanceManifest:
    """Build a manifest from JSON, rejecting missing or extra identity fields."""

    expected = {field.name for field in fields(UnattendedAcceptanceManifest)}
    if set(payload) != expected:
        raise ValueError("manifest must contain exactly the UnattendedAcceptanceManifest fields")
    values = dict(payload)
    checks = values.get("requested_checks")
    if not isinstance(checks, list) or not all(isinstance(check, str) for check in checks):
        raise ValueError("manifest requested_checks must be a list of strings")
    values["requested_checks"] = tuple(checks)
    for name in expected - {"requested_checks"}:
        if not isinstance(values[name], str):
            raise ValueError(f"manifest {name} must be a string")
    return UnattendedAcceptanceManifest(**values)


def _identity_reasons(
    manifest: UnattendedAcceptanceManifest,
    observed: ObservedRuntimeIdentity,
) -> list[str]:
    reasons: list[str] = []
    for name in _IDENTITY_FIELDS:
        expected: str = getattr(manifest, name)
        actual: str | None = getattr(observed, name)
        if actual is None:
            reasons.append(f"identity_unresolved:{name}")
            continue
        if name.endswith("_sha"):
            actual = actual.lower()
        if actual != expected:
            reasons.append(f"identity_mismatch:{name}")
    return reasons


def _golden_case(
    scenario_id: str,
    cases: tuple[GoldenResearchCase, ...] | None,
) -> GoldenResearchCase | None:
    if scenario_id != MONSTER_CASE_ID:
        return None
    for case in cases if cases is not None else default_golden_research_cases():
        if case.case_id == MONSTER_CASE_ID:
            return case
    return None


def _report_payload(
    report_build: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, list[str]]:
    if report_build is None:
        return None, ["research_report_artifact_missing"]
    report = report_build.get("report")
    if report_build.get("available") is not True or report_build.get("error_code") is not None:
        return None, ["research_report_unavailable"]
    if not isinstance(report, Mapping):
        return None, ["research_report_unavailable"]
    return report, []


def _report_contract_reasons(report: Mapping[str, Any], case: GoldenResearchCase) -> list[str]:
    reasons: list[str] = []
    if report.get("schema_version") != RESEARCH_REPORT_SCHEMA_VERSION:
        reasons.append("research_report_schema_mismatch")
    question = report.get("question")
    if not isinstance(question, str) or question.strip() != case.question:
        reasons.append("research_report_question_mismatch")
    if _nonblank(report.get("session_id")) is None:
        reasons.append("research_report_session_id_missing")
    state = report.get("research_state")
    if not isinstance(state, str) or state not in _KNOWN_RESEARCH_STATES:
        reasons.append("research_report_state_unknown")
    elif state in _NON_ANSWER_RESEARCH_STATES:
        reasons.append("research_report_state_not_answer")
    if _report_dimensions(report) is None:
        reasons.append("research_report_conclusion_rows_invalid")
    if _string_list(report.get("degraded_providers")) is None:
        reasons.append("research_report_degraded_providers_invalid")
    return reasons


def _cross_artifact_reasons(
    artifact: Mapping[str, Any] | None,
    snapshot: ResearchCaseRunSnapshot,
    report: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    snapshot_session = _nonblank(artifact.get("session_id")) if artifact is not None else None
    if snapshot_session is None or snapshot_session != _nonblank(report.get("session_id")):
        reasons.append("benchmark_snapshot_session_mismatch")
    report_dimensions = _report_dimensions(report)
    if report_dimensions is not None and not set(snapshot.covered_dimensions) <= report_dimensions:
        reasons.append("benchmark_dimensions_not_in_report")
    report_degraded = _string_list(report.get("degraded_providers"))
    snapshot_degraded = set(snapshot.reported_degraded_providers)
    if report_degraded is not None and set(report_degraded) != snapshot_degraded:
        reasons.append("benchmark_degraded_providers_disagree_with_report")
    return reasons


def _snapshot_from_artifact(
    artifact: Mapping[str, Any] | None,
) -> tuple[ResearchCaseRunSnapshot | None, list[str]]:
    if artifact is None:
        return None, ["benchmark_snapshot_missing"]

    reasons: list[str] = []
    allowed = {*_SNAPSHOT_FIELDS, "session_id"}
    if set(artifact) - allowed:
        reasons.append("benchmark_fact_unknown")
    if _nonblank(artifact.get("session_id")) is None:
        reasons.append("benchmark_fact_unresolved:session_id")

    values: dict[str, Any] = {}
    for name in _SNAPSHOT_FIELDS:
        value = artifact.get(name)
        if value is None:
            # Even list facts must be explicit (possibly empty); omission is unresolved.
            reasons.append(f"benchmark_fact_unresolved:{name}")
            continue
        parsed = _parse_snapshot_value(name, value)
        if parsed is None:
            reasons.append(f"benchmark_fact_invalid:{name}")
            continue
        values[name] = parsed

    if reasons:
        return None, reasons
    try:
        return ResearchCaseRunSnapshot(**values), []
    except ValueError:
        return None, ["benchmark_snapshot_invalid"]


def _parse_snapshot_value(name: str, value: object) -> object | None:
    if name == "case_id":
        return _nonblank(value)
    if name in _SNAPSHOT_TUPLE_FIELDS:
        items = _string_list(value)
        return tuple(items) if items is not None else None
    if name in _SNAPSHOT_INT_FIELDS:
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if name in _SNAPSHOT_BOOL_FIELDS:
        return value if isinstance(value, bool) else None
    if name == "source_field_gaps":
        return _source_field_gaps(value)
    return None


def _source_field_gaps(value: object) -> tuple[SourceFieldGap, ...] | None:
    if not isinstance(value, list):
        return None
    gaps: list[SourceFieldGap] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"source_id", "missing_fields"}:
            return None
        source_id = _nonblank(item.get("source_id"))
        missing = _string_list(item.get("missing_fields"))
        if source_id is None or missing is None:
            return None
        try:
            gaps.append(SourceFieldGap(source_id=source_id, missing_fields=tuple(missing)))
        except ValueError:
            return None
    return tuple(gaps)


def _report_dimensions(report: Mapping[str, Any]) -> set[str] | None:
    rows = report.get("conclusion_rows")
    if not isinstance(rows, list):
        return None
    dimensions: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        dimension = _nonblank(row.get("question_dimension"))
        if dimension is None:
            return None
        dimensions.add(dimension)
    return dimensions


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _nonblank(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _benchmark_payload(result: ResearchCaseBenchmarkResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    payload: dict[str, object] = {"case_id": result.case_id, "passes": result.passes}
    for name in _BENCHMARK_GUARD_FIELDS:
        value = getattr(result, name)
        if name == "source_field_gaps":
            payload[name] = [
                {"source_id": gap.source_id, "missing_fields": list(gap.missing_fields)}
                for gap in value
            ]
        elif isinstance(value, tuple):
            payload[name] = list(value)
        else:
            payload[name] = value
    return payload


app = typer.Typer(add_completion=False)

ManifestOption = Annotated[
    Path,
    typer.Option("--manifest", exists=True, dir_okay=False, help="Manifest JSON."),
]


@app.command()
def evaluate(
    manifest: ManifestOption,
    observed_identity: Annotated[
        Path | None,
        typer.Option("--observed-identity", dir_okay=False, help="Observed runtime JSON."),
    ] = None,
    worker_result: Annotated[
        Path | None,
        typer.Option("--worker-result", dir_okay=False, help="Core WorkerResult JSON."),
    ] = None,
    report_build: Annotated[
        Path | None,
        typer.Option("--report-build", dir_okay=False, help="ResearchReportBuildResult JSON."),
    ] = None,
    benchmark_snapshot: Annotated[
        Path | None,
        typer.Option("--benchmark-snapshot", dir_okay=False, help="Run snapshot JSON."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", dir_okay=False, help="Sanitized verdict JSON path."),
    ] = None,
) -> None:
    """Emit a sanitized Monster acceptance verdict; exit 0 only on PASS."""

    manifest_payload = _read_json_object(manifest)
    if manifest_payload is None:
        typer.echo("manifest is not a readable JSON object", err=True)
        raise typer.Exit(2)
    try:
        bound_manifest = manifest_from_mapping(manifest_payload)
    except ValueError as exc:
        typer.echo(f"manifest invalid: {exc}", err=True)
        raise typer.Exit(2) from exc

    verdict = evaluate_monster_acceptance(
        bound_manifest,
        observed_identity=ObservedRuntimeIdentity.from_mapping(
            _read_json_object(observed_identity)
        ),
        worker_result=_read_json_object(worker_result),
        report_build=_read_json_object(report_build),
        benchmark_snapshot=_read_json_object(benchmark_snapshot),
    )
    payload = verdict.to_json()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    if not verdict.passed:
        raise typer.Exit(1)


def _read_json_object(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "MONSTER_CASE_ID",
    "MonsterAcceptanceStatus",
    "MonsterAcceptanceVerdict",
    "ObservedRuntimeIdentity",
    "evaluate_monster_acceptance",
    "manifest_from_mapping",
]


if __name__ == "__main__":
    app()
