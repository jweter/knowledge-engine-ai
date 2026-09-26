"""Unattended Monster #79 acceptance bridge over existing research artifacts.

This module does not run research. It consumes artifacts already produced by the
normal path -- the `ke-ai research --format json` payload, a Research Report v1
`ResearchReport.to_dict()` document, and an optional structured benchmark-facts
document -- and scores them with the reviewed golden case in
:mod:`knowledge_engine_ai.research_case_benchmark`.

Authority boundaries:

- `UnattendedAcceptanceManifest` binds the exact AI/Core/Web SHAs and the local
  Ollama model/runtime. The runtime identity observed by the worker must equal the
  manifest, and the Core `WorkerResult` must validate against the manifest.
- `GoldenResearchCase` remains the only acceptance contract. The research question
  must be the reviewed case question verbatim.
- Benchmark facts are read only from structured fields. Covered dimensions,
  attempted/degraded providers, and discovery triggering are derived from the
  report and research payload; every other `ResearchCaseRunSnapshot` fact must be
  supplied explicitly by a structured facts document. Narrative prose is never
  parsed for benchmark facts.

Every missing artifact, unresolved fact, identity mismatch, or non-PASS worker
status fails closed: only a fully resolved, identity-bound, benchmark-passing run
can yield `PASS`. `PASS` covers the deterministic benchmark gate only; it is not
Product Reality and does not replace the Research Report v1 readability review.

The returned evidence is sanitized: it records identities, status, reason codes,
and golden-case identifiers, never questions, narratives, report prose, evidence
text, worker summaries, hosts, paths, or credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from knowledge_engine_ai.copilot.research_report import (
    _HEALTHY_PROVIDER_OUTCOMES,
    RESEARCH_REPORT_SCHEMA_VERSION,
)
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
MONSTER_ACCEPTANCE_EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_SCOPE = "deterministic_golden_research_case_benchmark"

RUNTIME_IDENTITY_FIELDS = ("ai_sha", "core_sha", "web_sha", "ollama_model", "ollama_runtime_id")

# Snapshot facts derived from the report/research payload. A facts document may
# not also supply them, so each fact has exactly one structured authority.
DERIVED_FACT_FIELDS = frozenset(
    {
        "covered_dimensions",
        "attempted_providers",
        "degraded_providers",
        "reported_degraded_providers",
        "discovery_triggered",
    }
)

_ID_TUPLE_FACT_FIELDS = (
    "covered_variants",
    "completed_search_tracks",
    "reviewed_source_ids",
    "represented_counterevidence_source_ids",
    "source_fields_audited_source_ids",
    "violated_inference_guard_ids",
)
_BOOL_FACT_FIELDS = ("direct_long_term_study_found", "direct_long_term_gap_reported")
_COUNT_FACT_FIELDS = (
    "initial_indexed_evidence_record_count",
    "factual_claim_count",
    "source_linked_factual_claim_count",
)
REQUIRED_FACT_FIELDS = (
    *_COUNT_FACT_FIELDS,
    *_ID_TUPLE_FACT_FIELDS,
    *_BOOL_FACT_FIELDS,
    "source_field_gaps",
)
_FACTS_BINDING_FIELDS = frozenset({"case_id", "session_id"})


class _AcceptanceFailure(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class MonsterAcceptanceEvidence:
    """Sanitized, publishable outcome of one unattended Monster acceptance run."""

    status: str
    reason_codes: tuple[str, ...]
    manifest: UnattendedAcceptanceManifest
    worker_request_id: str
    worker_status: str | None
    session_id: str | None
    unresolved_fact_fields: tuple[str, ...]
    benchmark: ResearchCaseBenchmarkResult | None

    @property
    def passes(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MONSTER_ACCEPTANCE_EVIDENCE_SCHEMA_VERSION,
            "case_id": MONSTER_CASE_ID,
            "evidence_scope": EVIDENCE_SCOPE,
            "product_reality_verified": False,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "identity": {
                "ai_sha": self.manifest.ai_sha,
                "core_sha": self.manifest.core_sha,
                "web_sha": self.manifest.web_sha,
                "core_branch": self.manifest.core_branch,
                "environment_id": self.manifest.environment_id,
                "created_at_utc": self.manifest.created_at_utc,
                "scenario_id": self.manifest.scenario_id,
                "ollama_model": self.manifest.ollama_model,
                "ollama_runtime_id": self.manifest.ollama_runtime_id,
                "identity_sha256": self.manifest.identity_sha256(),
            },
            "worker_request_id": self.worker_request_id,
            "worker_status": self.worker_status,
            "session_id": self.session_id,
            "unresolved_fact_fields": list(self.unresolved_fact_fields),
            "benchmark": None if self.benchmark is None else _benchmark_dict(self.benchmark),
        }


def evaluate_monster_acceptance(
    manifest: UnattendedAcceptanceManifest,
    *,
    worker_result: Mapping[str, Any] | None,
    observed_runtime_identity: Mapping[str, Any] | None,
    research_result: Mapping[str, Any] | None,
    research_report: Mapping[str, Any] | None,
    benchmark_facts: Mapping[str, Any] | None,
) -> MonsterAcceptanceEvidence:
    """Fail closed unless every artifact is present, bound, resolved, and passing."""

    case = _monster_case()
    request_id = str(manifest.core_worker_request()["request_id"])
    worker_status: str | None = None
    session_id: str | None = None
    unresolved: tuple[str, ...] = ()
    benchmark: ResearchCaseBenchmarkResult | None = None

    def outcome(status: str, *reasons: str) -> MonsterAcceptanceEvidence:
        return MonsterAcceptanceEvidence(
            status=status,
            reason_codes=reasons,
            manifest=manifest,
            worker_request_id=request_id,
            worker_status=worker_status,
            session_id=session_id,
            unresolved_fact_fields=unresolved,
            benchmark=benchmark,
        )

    if manifest.scenario_id != case.case_id:
        return outcome("FAIL", "manifest_scenario_not_monster_case")

    if worker_result is None:
        return outcome("ENVIRONMENT_FAILURE", "worker_result_missing")
    try:
        worker_status = manifest.validate_worker_result(worker_result)
    except ValueError:
        return outcome("FAIL", "worker_result_identity_mismatch")
    if worker_status != "PASS":
        return outcome(worker_status, "worker_status_not_pass")

    if observed_runtime_identity is None:
        return outcome("FAIL", "runtime_identity_missing")
    mismatched = [
        field
        for field in RUNTIME_IDENTITY_FIELDS
        if _normalized_identity(observed_runtime_identity.get(field), field)
        != getattr(manifest, field)
    ]
    if mismatched:
        return outcome("FAIL", *(f"runtime_identity_mismatch:{field}" for field in mismatched))

    try:
        session_id, discovery_triggered = _research_result_facts(research_result, case)
        derived = _report_facts(research_report, case, session_id)
        explicit, unresolved = _explicit_facts(benchmark_facts, case, session_id)
    except _AcceptanceFailure as failure:
        return outcome("FAIL", failure.reason_code)

    if unresolved:
        return outcome("FAIL", "benchmark_facts_unresolved")

    try:
        snapshot = ResearchCaseRunSnapshot(
            case_id=case.case_id,
            discovery_triggered=discovery_triggered,
            **derived,
            **explicit,
        )
        benchmark = evaluate_research_case(case, snapshot)
    except (TypeError, ValueError):
        return outcome("FAIL", "benchmark_facts_invalid")

    if not benchmark.passes:
        return outcome("FAIL", "golden_research_case_failed")
    return outcome("PASS")


def _monster_case() -> GoldenResearchCase:
    for case in default_golden_research_cases():
        if case.case_id == MONSTER_CASE_ID:
            return case
    raise RuntimeError(f"Reviewed golden research case {MONSTER_CASE_ID!r} is missing.")


def _normalized_identity(value: object, field: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized.lower() if field.endswith("_sha") else normalized


def _research_result_facts(
    payload: Mapping[str, Any] | None, case: GoldenResearchCase
) -> tuple[str, bool]:
    if payload is None:
        raise _AcceptanceFailure("research_result_missing")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise _AcceptanceFailure("research_result_malformed")
    if payload.get("question") != case.question:
        raise _AcceptanceFailure("research_question_not_golden_case")
    if payload.get("narrative_releaseable") is not True:
        raise _AcceptanceFailure("research_result_not_releaseable")
    if "discovery" not in payload:
        raise _AcceptanceFailure("research_result_malformed")
    discovery = payload["discovery"]
    if discovery is None:
        return session_id, False
    if not isinstance(discovery, Mapping) or not isinstance(discovery.get("triggered"), bool):
        raise _AcceptanceFailure("research_result_malformed")
    return session_id, discovery["triggered"]


def _report_facts(
    report: Mapping[str, Any] | None, case: GoldenResearchCase, session_id: str
) -> dict[str, Any]:
    if report is None:
        raise _AcceptanceFailure("research_report_missing")
    if report.get("schema_version") != RESEARCH_REPORT_SCHEMA_VERSION:
        raise _AcceptanceFailure("research_report_schema_unsupported")
    if report.get("question") != case.question:
        raise _AcceptanceFailure("research_question_not_golden_case")
    if report.get("session_id") != session_id:
        raise _AcceptanceFailure("research_report_session_mismatch")

    rows = report.get("conclusion_rows")
    statuses = report.get("provider_statuses")
    reported_degraded = report.get("degraded_providers")
    if not isinstance(rows, list) or not isinstance(statuses, list):
        raise _AcceptanceFailure("research_report_malformed")
    dimensions = [
        row.get("question_dimension") if isinstance(row, Mapping) else None for row in rows
    ]
    attempted: list[str] = []
    degraded: list[str] = []
    for status in statuses:
        if not isinstance(status, Mapping):
            raise _AcceptanceFailure("research_report_malformed")
        provider = status.get("provider")
        outcome = status.get("outcome")
        if not isinstance(provider, str) or not isinstance(status.get("attempted"), bool):
            raise _AcceptanceFailure("research_report_malformed")
        if outcome is not None and not isinstance(outcome, str):
            raise _AcceptanceFailure("research_report_malformed")
        if status["attempted"]:
            attempted.append(provider)
            if outcome not in _HEALTHY_PROVIDER_OUTCOMES:
                degraded.append(provider)
    return {
        "covered_dimensions": _string_tuple(dimensions, "research_report_malformed"),
        "attempted_providers": _string_tuple(attempted, "research_report_malformed"),
        "degraded_providers": _string_tuple(degraded, "research_report_malformed"),
        "reported_degraded_providers": _string_tuple(
            reported_degraded, "research_report_malformed"
        ),
    }


def _explicit_facts(
    facts: Mapping[str, Any] | None, case: GoldenResearchCase, session_id: str
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if facts is None:
        return {}, REQUIRED_FACT_FIELDS
    if set(facts) & DERIVED_FACT_FIELDS:
        raise _AcceptanceFailure("benchmark_facts_override_derived_fact")
    if set(facts) - set(REQUIRED_FACT_FIELDS) - _FACTS_BINDING_FIELDS:
        raise _AcceptanceFailure("benchmark_facts_unknown_field")
    if facts.get("case_id") != case.case_id or facts.get("session_id") != session_id:
        raise _AcceptanceFailure("benchmark_facts_identity_mismatch")

    unresolved = tuple(field for field in REQUIRED_FACT_FIELDS if facts.get(field) is None)
    if unresolved:
        return {}, unresolved

    resolved: dict[str, Any] = {}
    for field in _COUNT_FACT_FIELDS:
        value = facts[field]
        if not isinstance(value, int) or isinstance(value, bool):
            raise _AcceptanceFailure("benchmark_facts_invalid")
        resolved[field] = value
    for field in _BOOL_FACT_FIELDS:
        if not isinstance(facts[field], bool):
            raise _AcceptanceFailure("benchmark_facts_invalid")
        resolved[field] = facts[field]
    for field in _ID_TUPLE_FACT_FIELDS:
        resolved[field] = _string_tuple(facts[field], "benchmark_facts_invalid")
    gaps = facts["source_field_gaps"]
    if not isinstance(gaps, list):
        raise _AcceptanceFailure("benchmark_facts_invalid")
    parsed_gaps: list[SourceFieldGap] = []
    for gap in gaps:
        if (
            not isinstance(gap, Mapping)
            or gap.get("source_id") not in case.required_seed_source_ids
        ):
            raise _AcceptanceFailure("benchmark_facts_invalid")
        try:
            parsed_gaps.append(
                SourceFieldGap(
                    source_id=gap["source_id"],
                    missing_fields=_string_tuple(
                        gap.get("missing_fields"), "benchmark_facts_invalid"
                    ),
                )
            )
        except ValueError as exc:
            raise _AcceptanceFailure("benchmark_facts_invalid") from exc
    resolved["source_field_gaps"] = tuple(parsed_gaps)
    return resolved, ()


def _string_tuple(value: object, reason_code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _AcceptanceFailure(reason_code)
    return tuple(value)


def _benchmark_dict(result: ResearchCaseBenchmarkResult) -> dict[str, object]:
    return {
        "passes": result.passes,
        "missing_variants": list(result.missing_variants),
        "missing_dimensions": list(result.missing_dimensions),
        "missing_search_tracks": list(result.missing_search_tracks),
        "missing_seed_source_ids": list(result.missing_seed_source_ids),
        "missing_counterevidence_seed_source_ids": list(
            result.missing_counterevidence_seed_source_ids
        ),
        "missing_required_providers": list(result.missing_required_providers),
        "provider_count_shortfall": result.provider_count_shortfall,
        "unreported_degraded_providers": list(result.unreported_degraded_providers),
        "incorrectly_reported_degraded_providers": list(
            result.incorrectly_reported_degraded_providers
        ),
        "missing_source_field_audits": list(result.missing_source_field_audits),
        "source_field_gaps": [
            {"source_id": gap.source_id, "missing_fields": list(gap.missing_fields)}
            for gap in result.source_field_gaps
        ],
        "discovery_required_but_not_triggered": result.discovery_required_but_not_triggered,
        "long_term_gap_disclosure_missing": result.long_term_gap_disclosure_missing,
        "unlinked_factual_claim_count": result.unlinked_factual_claim_count,
        "violated_inference_guard_ids": list(result.violated_inference_guard_ids),
    }


__all__ = [
    "DERIVED_FACT_FIELDS",
    "MONSTER_CASE_ID",
    "REQUIRED_FACT_FIELDS",
    "RUNTIME_IDENTITY_FIELDS",
    "MonsterAcceptanceEvidence",
    "evaluate_monster_acceptance",
]
