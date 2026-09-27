from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from knowledge_engine_ai.monster_acceptance import (
    MONSTER_CASE_ID,
    MonsterAcceptanceStatus,
    MonsterAcceptanceVerdict,
    ObservedRuntimeIdentity,
    app,
    evaluate_monster_acceptance,
    manifest_from_mapping,
)
from knowledge_engine_ai.research_case_benchmark import default_golden_research_cases
from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

AI_SHA = "a" * 40
CORE_SHA = "b" * 40
WEB_SHA = "c" * 40
SESSION_ID = "session-monster-1"
PRIVATE_PROSE = "PRIVATE-REPORT-PROSE"
PRIVATE_SUMMARY = "C:/Users/someone/secret-token-summary"

CASE = next(case for case in default_golden_research_cases() if case.case_id == MONSTER_CASE_ID)


def _manifest_payload() -> dict[str, Any]:
    return {
        "ai_sha": AI_SHA,
        "core_sha": CORE_SHA,
        "web_sha": WEB_SHA,
        "core_branch": "main",
        "environment_id": "local-idle-worker",
        "created_at_utc": "2026-09-27T05:00:00+00:00",
        "scenario_id": MONSTER_CASE_ID,
        "ollama_model": "qwen3:8b",
        "ollama_runtime_id": "ollama-0.12.0-local",
        "requested_checks": ["preflight", "ollama_health", "monster_acceptance"],
    }


def _manifest(**overrides: Any) -> UnattendedAcceptanceManifest:
    return manifest_from_mapping({**_manifest_payload(), **overrides})


def _observed(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ai_sha": AI_SHA,
        "core_sha": CORE_SHA,
        "web_sha": WEB_SHA,
        "ollama_model": "qwen3:8b",
        "ollama_runtime_id": "ollama-0.12.0-local",
    }
    payload.update(overrides)
    return payload


def _worker_result(manifest: UnattendedAcceptanceManifest, **overrides: Any) -> dict[str, Any]:
    request = manifest.core_worker_request()
    payload: dict[str, Any] = {
        "request_id": request["request_id"],
        "repository": request["repository"],
        "exact_sha": request["exact_sha"],
        "environment_id": request["environment_id"],
        "status": "PASS",
        "completed_at_utc": "2026-09-27T05:30:00+00:00",
        "summary": PRIVATE_SUMMARY,
        "artifact_refs": [],
        "failure_class": None,
    }
    payload.update(overrides)
    return payload


def _report_build(**report_overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "question": CASE.question,
        "bottom_line": PRIVATE_PROSE,
        "conclusion_rows": [
            {
                "question_dimension": dimension,
                "conclusion": PRIVATE_PROSE,
                "certainty": "low",
                "certainty_rationale": PRIVATE_PROSE,
                "supporting_evidence_ids": ["er-1"],
                "contradicting_or_null_evidence_ids": [],
                "directness": "class_level",
                "missing_direct_evidence": "No direct one-year Monster trial.",
            }
            for dimension in CASE.required_dimensions
        ],
        "narrative_sections": [{"heading": "Summary", "body": PRIVATE_PROSE}],
        "missing_evidence": ["direct one-year Monster trial"],
        "direct_evidence_summary": PRIVATE_PROSE,
        "indirect_evidence_summary": PRIVATE_PROSE,
        "provider_coverage_completeness": "complete",
        "degraded_providers": [],
        "provider_statuses": [],
        "indexed_before_run_evidence_ids": [],
        "acquired_during_run_evidence_ids": ["er-1"],
        "limitations": [],
        "session_id": SESSION_ID,
        "research_state": "researched_answer",
    }
    report.update(report_overrides)
    return {"available": True, "error_code": None, "report": report}


def _snapshot(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": SESSION_ID,
        "case_id": CASE.case_id,
        "initial_indexed_evidence_record_count": 0,
        "discovery_triggered": True,
        "attempted_providers": ["pubmed", "semantic_scholar"],
        "degraded_providers": [],
        "reported_degraded_providers": [],
        "covered_variants": list(CASE.required_variants),
        "covered_dimensions": list(CASE.required_dimensions),
        "completed_search_tracks": list(CASE.required_search_tracks),
        "reviewed_source_ids": list(CASE.required_seed_source_ids),
        "represented_counterevidence_source_ids": list(CASE.counterevidence_seed_source_ids),
        "source_fields_audited_source_ids": list(CASE.required_seed_source_ids),
        "direct_long_term_study_found": False,
        "direct_long_term_gap_reported": True,
        "factual_claim_count": 12,
        "source_linked_factual_claim_count": 12,
        "source_field_gaps": [],
        "violated_inference_guard_ids": [],
    }
    payload.update(overrides)
    return payload


_DEFAULT: Any = object()


def _evaluate(
    *,
    manifest: UnattendedAcceptanceManifest | None = None,
    observed: dict[str, Any] | None = None,
    worker: Any = _DEFAULT,
    report: Any = _DEFAULT,
    snapshot: Any = _DEFAULT,
) -> MonsterAcceptanceVerdict:
    bound = manifest or _manifest()
    return evaluate_monster_acceptance(
        bound,
        observed_identity=ObservedRuntimeIdentity.from_mapping(observed or _observed()),
        worker_result=_worker_result(bound) if worker is _DEFAULT else worker,
        report_build=_report_build() if report is _DEFAULT else report,
        benchmark_snapshot=_snapshot() if snapshot is _DEFAULT else snapshot,
    )


def test_complete_bound_run_passes_and_records_exact_identity() -> None:
    verdict = _evaluate()

    assert verdict.status is MonsterAcceptanceStatus.PASS
    assert verdict.reasons == ()
    payload = verdict.to_dict()
    identity = payload["identity"]
    assert isinstance(identity, dict)
    assert identity["ai_sha"] == AI_SHA
    assert identity["core_sha"] == CORE_SHA
    assert identity["web_sha"] == WEB_SHA
    assert identity["ollama_model"] == "qwen3:8b"
    assert identity["ollama_runtime_id"] == "ollama-0.12.0-local"
    assert identity["core_request_id"] == verdict.manifest.core_worker_request()["request_id"]
    assert payload["research_session_id"] == SESSION_ID
    assert payload["worker_status"] == "PASS"


def test_verdict_publishes_only_sanitized_derived_evidence() -> None:
    serialized = _evaluate().to_json()

    assert PRIVATE_PROSE not in serialized
    assert PRIVATE_SUMMARY not in serialized
    assert CASE.question not in serialized
    assert "report_artifact_sha256" in json.loads(serialized)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ai_sha", "d" * 40),
        ("core_sha", "d" * 40),
        ("web_sha", "d" * 40),
        ("ollama_model", "llama3.1:8b"),
        ("ollama_runtime_id", "ollama-remote"),
    ],
)
def test_identity_mismatch_fails_closed(field: str, value: str) -> None:
    verdict = _evaluate(observed=_observed(**{field: value}))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert f"identity_mismatch:{field}" in verdict.reasons


@pytest.mark.parametrize("field", ["ai_sha", "core_sha", "web_sha", "ollama_model"])
def test_unobserved_identity_fails_closed(field: str) -> None:
    observed = _observed()
    del observed[field]

    verdict = _evaluate(observed=observed)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert f"identity_unresolved:{field}" in verdict.reasons


def test_identity_mismatch_is_not_downgraded_to_environment_failure() -> None:
    verdict = _evaluate(observed=_observed(web_sha="d" * 40), worker=None)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "identity_mismatch:web_sha" in verdict.reasons
    assert "worker_result_missing" in verdict.reasons


def test_missing_worker_result_is_environment_failure() -> None:
    verdict = _evaluate(worker=None)

    assert verdict.status is MonsterAcceptanceStatus.ENVIRONMENT_FAILURE
    assert verdict.reasons == ("worker_result_missing",)


def test_worker_result_for_other_sha_is_environment_failure() -> None:
    manifest = _manifest()
    verdict = _evaluate(manifest=manifest, worker=_worker_result(manifest, exact_sha="d" * 40))

    assert verdict.status is MonsterAcceptanceStatus.ENVIRONMENT_FAILURE
    assert "worker_result_invalid" in verdict.reasons


def test_worker_environment_failure_cannot_pass() -> None:
    manifest = _manifest()
    worker = _worker_result(manifest, status="ENVIRONMENT_FAILURE")

    verdict = _evaluate(manifest=manifest, worker=worker)

    assert verdict.status is MonsterAcceptanceStatus.ENVIRONMENT_FAILURE


@pytest.mark.parametrize("status", ["FAIL", "REVIEW_REQUIRED", "PRODUCT_REALITY_REQUIRED"])
def test_non_pass_worker_status_cannot_pass(status: str) -> None:
    manifest = _manifest()
    verdict = _evaluate(manifest=manifest, worker=_worker_result(manifest, status=status))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert f"worker_status_{status.lower()}" in verdict.reasons


def test_non_monster_scenario_cannot_pass() -> None:
    verdict = _evaluate(manifest=_manifest(scenario_id="research-report-v1"))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "scenario_not_monster_golden_case" in verdict.reasons


def test_missing_research_report_artifact_fails() -> None:
    verdict = _evaluate(report=None)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "research_report_artifact_missing" in verdict.reasons


def test_unavailable_research_report_fails() -> None:
    unavailable = {
        "available": False,
        "error_code": "research_report_generation_failed",
        "report": None,
    }

    verdict = _evaluate(report=unavailable)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "research_report_unavailable" in verdict.reasons


def test_report_for_different_question_fails() -> None:
    verdict = _evaluate(report=_report_build(question="Does coffee raise blood pressure?"))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "research_report_question_mismatch" in verdict.reasons


@pytest.mark.parametrize("state", ["researching", "research_required", "blocked"])
def test_non_answer_research_state_fails(state: str) -> None:
    verdict = _evaluate(report=_report_build(research_state=state))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "research_report_state_not_answer" in verdict.reasons


def test_unknown_research_state_fails() -> None:
    verdict = _evaluate(report=_report_build(research_state="done"))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "research_report_state_unknown" in verdict.reasons
    assert verdict.research_state is None


def test_missing_benchmark_snapshot_fails() -> None:
    verdict = _evaluate(snapshot=None)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_snapshot_missing" in verdict.reasons
    assert verdict.benchmark is None


@pytest.mark.parametrize(
    "field",
    ["covered_dimensions", "direct_long_term_gap_reported", "violated_inference_guard_ids"],
)
def test_unresolved_benchmark_fact_fails(field: str) -> None:
    snapshot = _snapshot()
    snapshot[field] = None

    verdict = _evaluate(snapshot=snapshot)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert f"benchmark_fact_unresolved:{field}" in verdict.reasons


def test_omitted_benchmark_fact_fails() -> None:
    snapshot = _snapshot()
    del snapshot["source_field_gaps"]

    verdict = _evaluate(snapshot=snapshot)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_fact_unresolved:source_field_gaps" in verdict.reasons


def test_unknown_benchmark_fact_fails() -> None:
    verdict = _evaluate(snapshot=_snapshot(narrative_says_pass=True))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_fact_unknown" in verdict.reasons


def test_wrongly_typed_benchmark_fact_fails() -> None:
    verdict = _evaluate(snapshot=_snapshot(discovery_triggered="yes"))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_fact_invalid:discovery_triggered" in verdict.reasons


def test_snapshot_from_other_session_fails() -> None:
    verdict = _evaluate(snapshot=_snapshot(session_id="another-session"))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_snapshot_session_mismatch" in verdict.reasons


def test_snapshot_dimension_absent_from_report_fails() -> None:
    report = _report_build()
    report["report"]["conclusion_rows"] = report["report"]["conclusion_rows"][:-1]

    verdict = _evaluate(report=report)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_dimensions_not_in_report" in verdict.reasons


def test_snapshot_degraded_providers_must_match_report() -> None:
    degraded = ["semantic_scholar"]
    snapshot = _snapshot(degraded_providers=degraded, reported_degraded_providers=degraded)

    verdict = _evaluate(snapshot=snapshot)

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_degraded_providers_disagree_with_report" in verdict.reasons


def test_golden_guard_failure_fails_with_guard_name() -> None:
    reviewed = list(CASE.required_seed_source_ids)[1:]

    verdict = _evaluate(snapshot=_snapshot(reviewed_source_ids=reviewed))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_guard_failed:missing_seed_source_ids" in verdict.reasons
    assert verdict.benchmark is not None
    assert not verdict.benchmark.passes


def test_unknown_inference_guard_violation_fails_closed() -> None:
    verdict = _evaluate(snapshot=_snapshot(violated_inference_guard_ids=["invented_guard"]))

    assert verdict.status is MonsterAcceptanceStatus.FAIL
    assert "benchmark_contract_violation" in verdict.reasons


def test_manifest_from_mapping_rejects_extra_fields() -> None:
    with pytest.raises(ValueError, match="exactly the UnattendedAcceptanceManifest fields"):
        manifest_from_mapping({**_manifest_payload(), "api_key": "x"})


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _cli_args(tmp_path: Path, *, include_report: bool = True) -> list[str]:
    manifest = _manifest()
    args = [
        "--manifest",
        str(_write(tmp_path / "manifest.json", _manifest_payload())),
        "--observed-identity",
        str(_write(tmp_path / "observed.json", _observed())),
        "--worker-result",
        str(_write(tmp_path / "worker.json", _worker_result(manifest))),
        "--benchmark-snapshot",
        str(_write(tmp_path / "snapshot.json", _snapshot())),
        "--output",
        str(tmp_path / "out" / "verdict.json"),
    ]
    report_path = tmp_path / "report.json"
    if include_report:
        _write(report_path, _report_build())
    return [*args, "--report-build", str(report_path)]


def test_cli_writes_verdict_and_exits_zero_only_on_pass(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, _cli_args(tmp_path))

    assert result.exit_code == 0, result.output
    verdict = json.loads((tmp_path / "out" / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "PASS"


def test_cli_missing_report_file_fails_closed(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, _cli_args(tmp_path, include_report=False))

    assert result.exit_code == 1
    verdict = json.loads((tmp_path / "out" / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "FAIL"
    assert "research_report_artifact_missing" in verdict["reasons"]
