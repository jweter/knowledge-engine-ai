from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from knowledge_engine_ai.monster_acceptance import (
    MONSTER_CASE_ID,
    MonsterAcceptanceRecord,
    app,
    evaluate_monster_acceptance,
)
from knowledge_engine_ai.research_case_benchmark import default_golden_research_cases
from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

AI_SHA = "a" * 40
CORE_SHA = "b" * 40
WEB_SHA = "c" * 40
SESSION_ID = "session-123"
SECRET_NARRATIVE = "PRIVATE narrative text that must never leave the local boundary"


def _case() -> Any:
    return next(c for c in default_golden_research_cases() if c.case_id == MONSTER_CASE_ID)


def _manifest() -> UnattendedAcceptanceManifest:
    return UnattendedAcceptanceManifest(
        ai_sha=AI_SHA,
        core_sha=CORE_SHA,
        web_sha=WEB_SHA,
        core_branch="main",
        environment_id="local-idle-worker",
        created_at_utc="2026-09-26T12:00:00+00:00",
        scenario_id="monster-energy-bp-one-year",
        ollama_model="qwen3:8b",
        ollama_runtime_id="ollama-0.12.3",
        requested_checks=("preflight", "ollama_health", "monster_research"),
    )


def _observed() -> dict[str, Any]:
    return {
        "ai_sha": AI_SHA,
        "core_sha": CORE_SHA,
        "web_sha": WEB_SHA,
        "ollama_model": "qwen3:8b",
        "ollama_runtime_id": "ollama-0.12.3",
    }


def _worker_result(manifest: UnattendedAcceptanceManifest, status: str = "PASS") -> dict[str, Any]:
    request = manifest.core_worker_request()
    return {
        "request_id": request["request_id"],
        "repository": request["repository"],
        "exact_sha": request["exact_sha"],
        "environment_id": request["environment_id"],
        "status": status,
        "completed_at_utc": "2026-09-26T12:30:00+00:00",
        "summary": "worker summary C:\\Users\\private\\path",
        "artifact_refs": [],
        "failure_class": None,
    }


def _research_result() -> dict[str, Any]:
    return {
        "session_id": SESSION_ID,
        "question": _case().question,
        "narrative": SECRET_NARRATIVE,
        "narrative_releaseable": True,
        "close_complete": True,
        "close_status": "closed",
    }


def _research_report() -> dict[str, Any]:
    case = _case()
    return {
        "schema_version": 1,
        "question": case.question,
        "bottom_line": SECRET_NARRATIVE,
        "conclusion_rows": [
            {"question_dimension": dimension, "conclusion": SECRET_NARRATIVE}
            for dimension in case.required_dimensions
        ],
        "narrative_sections": [{"heading": "h", "body": SECRET_NARRATIVE}],
        "missing_evidence": ["No direct one-year Monster trial was found."],
        "direct_evidence_summary": SECRET_NARRATIVE,
        "indirect_evidence_summary": SECRET_NARRATIVE,
        "provider_coverage_completeness": "complete",
        "degraded_providers": [],
        "provider_statuses": [],
        "indexed_before_run_evidence_ids": [],
        "acquired_during_run_evidence_ids": ["ev-1"],
        "limitations": [],
        "session_id": SESSION_ID,
        "research_state": "complete",
    }


def _snapshot() -> dict[str, Any]:
    case = _case()
    return {
        "case_id": case.case_id,
        "initial_indexed_evidence_record_count": 0,
        "discovery_triggered": True,
        "attempted_providers": ["pubmed", "openalex"],
        "degraded_providers": [],
        "reported_degraded_providers": [],
        "covered_variants": list(case.required_variants),
        "covered_dimensions": list(case.required_dimensions),
        "completed_search_tracks": list(case.required_search_tracks),
        "reviewed_source_ids": list(case.required_seed_source_ids),
        "represented_counterevidence_source_ids": list(case.counterevidence_seed_source_ids),
        "source_fields_audited_source_ids": list(case.required_seed_source_ids),
        "direct_long_term_study_found": False,
        "direct_long_term_gap_reported": True,
        "factual_claim_count": 10,
        "source_linked_factual_claim_count": 10,
        "source_field_gaps": [],
        "violated_inference_guard_ids": [],
    }


def _evaluate(**overrides: Any) -> MonsterAcceptanceRecord:
    manifest = _manifest()
    values: dict[str, Any] = {
        "manifest": manifest,
        "observed_identity": _observed(),
        "worker_result": _worker_result(manifest),
        "research_result": _research_result(),
        "research_report": _research_report(),
        "benchmark_snapshot": _snapshot(),
    }
    values.update(overrides)
    return evaluate_monster_acceptance(**values)


def test_complete_bound_run_passes_and_records_exact_identity() -> None:
    record = _evaluate()

    assert record.status == "PASS", record.reason_codes
    identity = record.manifest_identity
    assert identity is not None
    assert identity["ai_sha"] == AI_SHA
    assert identity["core_sha"] == CORE_SHA
    assert identity["web_sha"] == WEB_SHA
    assert identity["ollama_model"] == "qwen3:8b"
    assert identity["ollama_runtime_id"] == "ollama-0.12.3"
    assert record.observed_identity == _observed()
    assert record.benchmark is not None
    assert record.benchmark["passes"] is True
    payload = record.to_dict()
    assert payload["manual_readability_review_required"] is True
    assert payload["product_reality_claimed"] is False


@pytest.mark.parametrize("key", ["ai_sha", "core_sha", "web_sha"])
def test_repository_sha_mismatch_fails_closed(key: str) -> None:
    observed = {**_observed(), key: "d" * 40}

    record = _evaluate(observed_identity=observed)

    assert record.status == "FAIL"
    assert f"identity_mismatch:{key}" in record.reason_codes


@pytest.mark.parametrize("key", ["ollama_model", "ollama_runtime_id"])
def test_ollama_identity_mismatch_fails_closed(key: str) -> None:
    observed = {**_observed(), key: "other"}

    record = _evaluate(observed_identity=observed)

    assert record.status == "FAIL"
    assert f"identity_mismatch:{key}" in record.reason_codes


def test_missing_observed_identity_field_is_unresolved() -> None:
    observed = _observed()
    del observed["web_sha"]

    record = _evaluate(observed_identity=observed)

    assert record.status == "FAIL"
    assert "observed_identity_unresolved:web_sha" in record.reason_codes


def test_worker_result_for_other_core_sha_fails_closed() -> None:
    manifest = _manifest()
    worker = {**_worker_result(manifest), "exact_sha": "d" * 40}

    record = _evaluate(manifest=manifest, worker_result=worker)

    assert record.status == "FAIL"
    assert "worker_result_invalid" in record.reason_codes


def test_worker_environment_failure_never_passes() -> None:
    manifest = _manifest()

    record = _evaluate(
        manifest=manifest, worker_result=_worker_result(manifest, "ENVIRONMENT_FAILURE")
    )

    assert record.status == "ENVIRONMENT_FAILURE"
    assert "worker_environment_failure" in record.reason_codes


@pytest.mark.parametrize("status", ["FAIL", "REVIEW_REQUIRED", "PRODUCT_REALITY_REQUIRED"])
def test_non_pass_worker_status_fails(status: str) -> None:
    manifest = _manifest()

    record = _evaluate(manifest=manifest, worker_result=_worker_result(manifest, status))

    assert record.status == "FAIL"
    assert f"worker_status:{status}" in record.reason_codes


@pytest.mark.parametrize(
    ("argument", "code"),
    [
        ("manifest", "manifest_missing"),
        ("observed_identity", "observed_identity_missing"),
        ("worker_result", "worker_result_missing"),
        ("research_result", "research_result_missing"),
        ("research_report", "research_report_missing"),
        ("benchmark_snapshot", "benchmark_snapshot_missing"),
    ],
)
def test_missing_artifact_fails_closed(argument: str, code: str) -> None:
    record = _evaluate(**{argument: None})

    assert record.status == "FAIL"
    assert code in record.reason_codes


def test_unreleased_or_unclosed_research_session_fails() -> None:
    research = {**_research_result(), "narrative_releaseable": False, "close_complete": False}

    record = _evaluate(research_result=research)

    assert record.status == "FAIL"
    assert "research_narrative_not_releaseable" in record.reason_codes
    assert "research_session_not_closed" in record.reason_codes


def test_report_from_other_session_or_question_fails() -> None:
    report = {**_research_report(), "session_id": "other", "question": "Another question?"}

    record = _evaluate(research_report=report)

    assert record.status == "FAIL"
    assert "research_report_session_mismatch" in record.reason_codes
    assert "research_report_question_mismatch" in record.reason_codes


@pytest.mark.parametrize(
    "field",
    ["discovery_triggered", "factual_claim_count", "covered_dimensions", "source_field_gaps"],
)
def test_null_benchmark_fact_is_unresolved_not_pass(field: str) -> None:
    snapshot = {**_snapshot(), field: None}

    record = _evaluate(benchmark_snapshot=snapshot)

    assert record.status == "FAIL"
    assert f"benchmark_fact_unresolved:{field}" in record.reason_codes
    assert record.benchmark is None


def test_absent_benchmark_fact_is_unresolved_not_defaulted() -> None:
    snapshot = _snapshot()
    del snapshot["violated_inference_guard_ids"]

    record = _evaluate(benchmark_snapshot=snapshot)

    assert record.status == "FAIL"
    assert "benchmark_fact_unresolved:violated_inference_guard_ids" in record.reason_codes


def test_bool_masquerading_as_count_is_unresolved() -> None:
    snapshot = {**_snapshot(), "factual_claim_count": True}

    record = _evaluate(benchmark_snapshot=snapshot)

    assert "benchmark_fact_unresolved:factual_claim_count" in record.reason_codes


def test_unknown_benchmark_field_fails_closed() -> None:
    snapshot = {**_snapshot(), "narrative_says_pass": True}

    record = _evaluate(benchmark_snapshot=snapshot)

    assert record.status == "FAIL"
    assert "benchmark_snapshot_unknown_field:narrative_says_pass" in record.reason_codes


def test_unknown_inference_guard_violation_fails_closed() -> None:
    snapshot = {**_snapshot(), "violated_inference_guard_ids": ["unreviewed_guard"]}

    record = _evaluate(benchmark_snapshot=snapshot)

    assert record.status == "FAIL"
    assert "benchmark_snapshot_invalid" in record.reason_codes


def test_benchmark_gap_is_reported_by_existing_scorer() -> None:
    case = _case()
    snapshot = {**_snapshot(), "reviewed_source_ids": list(case.required_seed_source_ids[1:])}
    snapshot["represented_counterevidence_source_ids"] = [
        source
        for source in case.counterevidence_seed_source_ids
        if source in snapshot["reviewed_source_ids"]
    ]

    record = _evaluate(benchmark_snapshot=snapshot)

    assert record.status == "FAIL"
    assert "benchmark_failed:missing_seed_source_ids" in record.reason_codes
    assert record.benchmark is not None
    assert record.benchmark["missing_seed_source_ids"] == [case.required_seed_source_ids[0]]


def test_snapshot_dimension_not_backed_by_report_row_fails() -> None:
    report = _research_report()
    report["conclusion_rows"] = report["conclusion_rows"][1:]

    record = _evaluate(research_report=report)

    dimension = _case().required_dimensions[0]
    assert record.status == "FAIL"
    assert f"benchmark_dimension_absent_from_report:{dimension}" in record.reason_codes


def test_degraded_provider_disagreement_with_report_fails() -> None:
    report = {**_research_report(), "degraded_providers": ["openalex"]}

    record = _evaluate(research_report=report)

    assert record.status == "FAIL"
    assert "benchmark_degraded_providers_disagree_with_report" in record.reason_codes


def test_record_excludes_prose_and_worker_summary() -> None:
    serialized = _evaluate().to_json()

    assert "PRIVATE" not in serialized
    assert "private\\\\path" not in serialized
    assert "No direct one-year Monster trial" not in serialized
    assert "ev-1" not in serialized


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    manifest = _manifest()
    documents: dict[str, Any] = {
        "manifest": {**manifest.__dict__, "requested_checks": list(manifest.requested_checks)},
        "observed-identity": _observed(),
        "worker-result": _worker_result(manifest),
        "research-result": _research_result(),
        "research-report": _research_report(),
        "benchmark-snapshot": _snapshot(),
    }
    paths: dict[str, Path] = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    return paths


def _cli_args(paths: dict[str, Path], output: Path) -> list[str]:
    args: list[str] = []
    for name, path in paths.items():
        args.extend([f"--{name}", str(path)])
    return [*args, "--output", str(output)]


def test_cli_writes_sanitized_pass_record(tmp_path: Path) -> None:
    output = tmp_path / "out" / "record.json"

    result = CliRunner().invoke(app, _cli_args(_write_inputs(tmp_path), output))

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert "PRIVATE" not in output.read_text(encoding="utf-8")


def test_cli_unreadable_artifact_fails_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    paths["research-report"].write_text("{not json", encoding="utf-8")
    output = tmp_path / "record.json"

    result = CliRunner().invoke(app, _cli_args(paths, output))

    assert result.exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert "research_report_unreadable" in payload["reason_codes"]


def test_cli_manifest_with_unexpected_field_fails_closed(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["extra"] = "value"
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "record.json"

    result = CliRunner().invoke(app, _cli_args(paths, output))

    assert result.exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "manifest_invalid" in payload["reason_codes"]
    assert payload["status"] == "FAIL"
