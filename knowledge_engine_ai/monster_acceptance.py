"""Local unattended Monster #79 acceptance bridge.

This module joins three existing authorities without creating a second research
pipeline:

* :class:`~knowledge_engine_ai.unattended_acceptance.UnattendedAcceptanceManifest`
  binds the exact AI/Core/Web SHAs, the local Ollama runtime/model, and the Core
  unattended-worker request/result identity.
* The ``ke-ai research --format json`` payload and the Research Report v1
  ``ResearchReport.to_dict()`` artifact remain the research-session authority.
* :mod:`knowledge_engine_ai.research_case_benchmark` remains the golden-case
  scoring authority. Benchmark facts come only from a structured
  ``ResearchCaseRunSnapshot`` mapping; narrative prose is never scraped.

Every gap fails closed: missing artifacts, unresolved (absent/``null``/mistyped)
benchmark facts, identity drift, and worker/environment failures can never
become ``PASS``. A deterministic ``PASS`` is not Product Reality evidence and
does not replace the manual readability/usefulness review required by the
Research Report v1 contract.

The emitted record is sanitized derived evidence only: identities, stable
reason codes, counts, and benchmark gap identifiers. It never copies narrative
text, report prose, evidence text, worker summaries, hosts, or file paths.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Annotated, Any

import typer

from knowledge_engine_ai.copilot.research_report import RESEARCH_REPORT_SCHEMA_VERSION
from knowledge_engine_ai.research_case_benchmark import (
    GoldenResearchCase,
    ResearchCaseBenchmarkResult,
    ResearchCaseRunSnapshot,
    SourceFieldGap,
    default_golden_research_cases,
    evaluate_research_case,
)
from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

MONSTER_ACCEPTANCE_SCHEMA_VERSION = 1
MONSTER_CASE_ID = "monster-energy-bp-one-year"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"

_IDENTITY_FIELDS = ("ai_sha", "core_sha", "web_sha", "ollama_model", "ollama_runtime_id")
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
    {
        "discovery_triggered",
        "direct_long_term_study_found",
        "direct_long_term_gap_reported",
    }
)
_BENCHMARK_GAP_FIELDS = (
    "missing_variants",
    "missing_dimensions",
    "missing_search_tracks",
    "missing_seed_source_ids",
    "missing_counterevidence_seed_source_ids",
    "missing_required_providers",
    "provider_count_shortfall",
    "unreported_degraded_providers",
    "incorrectly_reported_degraded_providers",
    "missing_source_field_audits",
    "source_field_gaps",
    "discovery_required_but_not_triggered",
    "long_term_gap_disclosure_missing",
    "unlinked_factual_claim_count",
    "violated_inference_guard_ids",
)


@dataclass(frozen=True)
class MonsterAcceptanceRecord:
    """Sanitized, derived outcome of one unattended Monster acceptance evaluation."""

    status: str
    reason_codes: tuple[str, ...]
    case_id: str
    manifest_identity: Mapping[str, object] | None
    observed_identity: Mapping[str, str] | None
    worker_status: str | None
    session_id: str | None
    research_state: str | None
    report_conclusion_row_count: int | None
    report_missing_evidence_count: int | None
    benchmark: Mapping[str, object] | None

    @property
    def passes(self) -> bool:
        return self.status == STATUS_PASS

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MONSTER_ACCEPTANCE_SCHEMA_VERSION,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "case_id": self.case_id,
            "manifest_identity": (
                None if self.manifest_identity is None else dict(self.manifest_identity)
            ),
            "observed_identity": (
                None if self.observed_identity is None else dict(self.observed_identity)
            ),
            "worker_status": self.worker_status,
            "session_id": self.session_id,
            "research_state": self.research_state,
            "report_conclusion_row_count": self.report_conclusion_row_count,
            "report_missing_evidence_count": self.report_missing_evidence_count,
            "benchmark": None if self.benchmark is None else dict(self.benchmark),
            "manual_readability_review_required": True,
            "product_reality_claimed": False,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_monster_acceptance(
    *,
    manifest: UnattendedAcceptanceManifest | None,
    observed_identity: Mapping[str, Any] | None,
    worker_result: Mapping[str, Any] | None,
    research_result: Mapping[str, Any] | None,
    research_report: Mapping[str, Any] | None,
    benchmark_snapshot: Mapping[str, Any] | None,
    case: GoldenResearchCase | None = None,
) -> MonsterAcceptanceRecord:
    """Evaluate one unattended local Monster run; any gap fails closed."""

    golden = case if case is not None else _monster_case()
    reasons: list[str] = []
    environment_failure = False

    manifest_identity: dict[str, object] | None = None
    if manifest is None:
        reasons.append("manifest_missing")
    else:
        request = manifest.core_worker_request()
        manifest_identity = {
            "ai_sha": manifest.ai_sha,
            "core_sha": manifest.core_sha,
            "web_sha": manifest.web_sha,
            "core_branch": manifest.core_branch,
            "environment_id": manifest.environment_id,
            "scenario_id": manifest.scenario_id,
            "ollama_model": manifest.ollama_model,
            "ollama_runtime_id": manifest.ollama_runtime_id,
            "created_at_utc": manifest.created_at_utc,
            "request_id": request["request_id"],
            "identity_sha256": manifest.identity_sha256(),
        }

    observed = _observed_identity(observed_identity, reasons)
    if manifest is not None and observed is not None:
        for key in _IDENTITY_FIELDS:
            if observed[key] != getattr(manifest, key):
                reasons.append(f"identity_mismatch:{key}")

    worker_status: str | None = None
    if worker_result is None:
        reasons.append("worker_result_missing")
    elif manifest is not None:
        try:
            worker_status = manifest.validate_worker_result(worker_result)
        except ValueError:
            reasons.append("worker_result_invalid")
        else:
            if worker_status == STATUS_ENVIRONMENT_FAILURE:
                environment_failure = True
                reasons.append("worker_environment_failure")
            elif worker_status != STATUS_PASS:
                reasons.append(f"worker_status:{worker_status}")

    session_id = _research_session(research_result, reasons)
    report_facts = _report_facts(research_report, golden, session_id, reasons)
    benchmark = _benchmark(benchmark_snapshot, golden, report_facts, reasons)

    if not reasons:
        status = STATUS_PASS
    elif environment_failure:
        status = STATUS_ENVIRONMENT_FAILURE
    else:
        status = STATUS_FAIL

    return MonsterAcceptanceRecord(
        status=status,
        reason_codes=tuple(reasons),
        case_id=golden.case_id,
        manifest_identity=manifest_identity,
        observed_identity=observed,
        worker_status=worker_status,
        session_id=session_id,
        research_state=None if report_facts is None else report_facts.research_state,
        report_conclusion_row_count=None if report_facts is None else len(report_facts.dimensions),
        report_missing_evidence_count=(
            None if report_facts is None else report_facts.missing_evidence_count
        ),
        benchmark=benchmark,
    )


@dataclass(frozen=True)
class _ReportFacts:
    research_state: str
    dimensions: tuple[str, ...]
    degraded_providers: tuple[str, ...]
    missing_evidence_count: int


def _monster_case() -> GoldenResearchCase:
    for case in default_golden_research_cases():
        if case.case_id == MONSTER_CASE_ID:
            return case
    raise ValueError(f"Reviewed golden research case {MONSTER_CASE_ID!r} is unavailable.")


def _observed_identity(
    payload: Mapping[str, Any] | None, reasons: list[str]
) -> dict[str, str] | None:
    if payload is None:
        reasons.append("observed_identity_missing")
        return None
    observed: dict[str, str] = {}
    for key in _IDENTITY_FIELDS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"observed_identity_unresolved:{key}")
            continue
        normalized = value.strip()
        observed[key] = normalized.lower() if key.endswith("_sha") else normalized
    return observed if len(observed) == len(_IDENTITY_FIELDS) else None


def _research_session(payload: Mapping[str, Any] | None, reasons: list[str]) -> str | None:
    if payload is None:
        reasons.append("research_result_missing")
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        reasons.append("research_result_unresolved:session_id")
        session_id = None
    releaseable = payload.get("narrative_releaseable")
    if not isinstance(releaseable, bool):
        reasons.append("research_result_unresolved:narrative_releaseable")
    elif not releaseable:
        reasons.append("research_narrative_not_releaseable")
    close_complete = payload.get("close_complete")
    if not isinstance(close_complete, bool):
        reasons.append("research_result_unresolved:close_complete")
    elif not close_complete:
        reasons.append("research_session_not_closed")
    return session_id


def _report_facts(
    payload: Mapping[str, Any] | None,
    case: GoldenResearchCase,
    session_id: str | None,
    reasons: list[str],
) -> _ReportFacts | None:
    if payload is None:
        reasons.append("research_report_missing")
        return None
    start = len(reasons)
    if payload.get("schema_version") != RESEARCH_REPORT_SCHEMA_VERSION:
        reasons.append("research_report_schema_mismatch")
    question = payload.get("question")
    if not isinstance(question, str) or question.strip() != case.question.strip():
        reasons.append("research_report_question_mismatch")
    report_session = payload.get("session_id")
    if not isinstance(report_session, str) or not report_session.strip():
        reasons.append("research_report_unresolved:session_id")
    elif session_id is not None and report_session != session_id:
        reasons.append("research_report_session_mismatch")
    research_state = payload.get("research_state")
    if not isinstance(research_state, str) or not research_state.strip():
        reasons.append("research_report_unresolved:research_state")

    dimensions: list[str] = []
    rows = payload.get("conclusion_rows")
    if not isinstance(rows, list) or not rows:
        reasons.append("research_report_unresolved:conclusion_rows")
    else:
        for row in rows:
            dimension = row.get("question_dimension") if isinstance(row, Mapping) else None
            if not isinstance(dimension, str) or not dimension.strip():
                reasons.append("research_report_unresolved:question_dimension")
                break
            dimensions.append(dimension)
    degraded = _string_list(payload.get("degraded_providers"))
    if degraded is None:
        reasons.append("research_report_unresolved:degraded_providers")
    missing_evidence = _string_list(payload.get("missing_evidence"))
    if missing_evidence is None:
        reasons.append("research_report_unresolved:missing_evidence")

    if len(reasons) != start or degraded is None or missing_evidence is None:
        return None
    assert isinstance(research_state, str)
    return _ReportFacts(
        research_state=research_state,
        dimensions=tuple(dimensions),
        degraded_providers=degraded,
        missing_evidence_count=len(missing_evidence),
    )


def _benchmark(
    payload: Mapping[str, Any] | None,
    case: GoldenResearchCase,
    report_facts: _ReportFacts | None,
    reasons: list[str],
) -> dict[str, object] | None:
    if payload is None:
        reasons.append("benchmark_snapshot_missing")
        return None
    snapshot = _parse_snapshot(payload, reasons)
    if snapshot is None:
        return None
    try:
        result = evaluate_research_case(case, snapshot)
    except ValueError:
        reasons.append("benchmark_snapshot_invalid")
        return None

    for name in _BENCHMARK_GAP_FIELDS:
        if getattr(result, name):
            reasons.append(f"benchmark_failed:{name}")

    if report_facts is not None:
        report_dimensions = set(report_facts.dimensions)
        for dimension in snapshot.covered_dimensions:
            if dimension not in report_dimensions:
                reasons.append(f"benchmark_dimension_absent_from_report:{dimension}")
        if set(snapshot.reported_degraded_providers) != set(report_facts.degraded_providers):
            reasons.append("benchmark_degraded_providers_disagree_with_report")

    return _benchmark_payload(result)


def _parse_snapshot(
    payload: Mapping[str, Any], reasons: list[str]
) -> ResearchCaseRunSnapshot | None:
    expected = {field.name for field in fields(ResearchCaseRunSnapshot)}
    start = len(reasons)
    for key in sorted(set(payload) - expected):
        reasons.append(f"benchmark_snapshot_unknown_field:{key}")

    values: dict[str, object] = {}
    for name in sorted(expected):
        raw = payload.get(name)
        value: object
        if name == "case_id":
            value = raw if isinstance(raw, str) and raw.strip() else None
        elif name in _SNAPSHOT_INT_FIELDS:
            value = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        elif name in _SNAPSHOT_BOOL_FIELDS:
            value = raw if isinstance(raw, bool) else None
        elif name in _SNAPSHOT_TUPLE_FIELDS:
            value = _string_list(raw)
        else:
            value = _source_field_gaps(raw)
        if value is None:
            reasons.append(f"benchmark_fact_unresolved:{name}")
        values[name] = value

    if len(reasons) != start:
        return None
    try:
        return ResearchCaseRunSnapshot(**values)  # type: ignore[arg-type]
    except ValueError:
        reasons.append("benchmark_snapshot_invalid")
        return None


def _source_field_gaps(raw: object) -> tuple[SourceFieldGap, ...] | None:
    if not isinstance(raw, list):
        return None
    gaps: list[SourceFieldGap] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"source_id", "missing_fields"}:
            return None
        source_id = item["source_id"]
        missing_fields = _string_list(item["missing_fields"])
        if not isinstance(source_id, str) or missing_fields is None:
            return None
        try:
            gaps.append(SourceFieldGap(source_id=source_id, missing_fields=missing_fields))
        except ValueError:
            return None
    return tuple(gaps)


def _string_list(raw: object) -> tuple[str, ...] | None:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return None
    return tuple(raw)


def _benchmark_payload(result: ResearchCaseBenchmarkResult) -> dict[str, object]:
    payload: dict[str, object] = {"case_id": result.case_id, "passes": result.passes}
    for name in _BENCHMARK_GAP_FIELDS:
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


@app.command()
def evaluate(
    manifest: Annotated[
        Path | None, typer.Option("--manifest", dir_okay=False, help="Manifest JSON.")
    ] = None,
    observed_identity: Annotated[
        Path | None,
        typer.Option("--observed-identity", dir_okay=False, help="Observed runtime identity."),
    ] = None,
    worker_result: Annotated[
        Path | None, typer.Option("--worker-result", dir_okay=False, help="Core WorkerResult.")
    ] = None,
    research_result: Annotated[
        Path | None,
        typer.Option("--research-result", dir_okay=False, help="`ke-ai research` JSON payload."),
    ] = None,
    research_report: Annotated[
        Path | None,
        typer.Option("--research-report", dir_okay=False, help="ResearchReport v1 JSON."),
    ] = None,
    benchmark_snapshot: Annotated[
        Path | None,
        typer.Option("--benchmark-snapshot", dir_okay=False, help="ResearchCaseRunSnapshot JSON."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Sanitized record path; stdout if omitted.")
    ] = None,
) -> None:
    """Evaluate one unattended Monster run; exit non-zero unless it is PASS."""

    reasons: list[str] = []
    parsed_manifest = _load_manifest(manifest, reasons)
    record = evaluate_monster_acceptance(
        manifest=parsed_manifest,
        observed_identity=_load_object(observed_identity, "observed_identity", reasons),
        worker_result=_load_object(worker_result, "worker_result", reasons),
        research_result=_load_object(research_result, "research_result", reasons),
        research_report=_load_object(research_report, "research_report", reasons),
        benchmark_snapshot=_load_object(benchmark_snapshot, "benchmark_snapshot", reasons),
    )
    if reasons:
        record = replace(
            record,
            status=STATUS_FAIL if record.status == STATUS_PASS else record.status,
            reason_codes=(*reasons, *record.reason_codes),
        )
    payload = record.to_json()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        typer.echo(payload, nl=False)
    if not record.passes:
        raise typer.Exit(1)


def _load_object(path: Path | None, label: str, reasons: list[str]) -> Mapping[str, Any] | None:
    if path is None:
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reasons.append(f"{label}_unreadable")
        return None
    if not isinstance(loaded, dict):
        reasons.append(f"{label}_unreadable")
        return None
    return loaded


def _load_manifest(path: Path | None, reasons: list[str]) -> UnattendedAcceptanceManifest | None:
    raw = _load_object(path, "manifest", reasons)
    if raw is None:
        return None
    expected = {field.name for field in fields(UnattendedAcceptanceManifest)}
    checks = raw.get("requested_checks")
    if set(raw) != expected or not isinstance(checks, list):
        reasons.append("manifest_invalid")
        return None
    try:
        return UnattendedAcceptanceManifest(**{**raw, "requested_checks": tuple(checks)})
    except (TypeError, ValueError, AttributeError):
        reasons.append("manifest_invalid")
        return None


__all__ = [
    "MONSTER_ACCEPTANCE_SCHEMA_VERSION",
    "MONSTER_CASE_ID",
    "MonsterAcceptanceRecord",
    "evaluate_monster_acceptance",
]


if __name__ == "__main__":
    app()
