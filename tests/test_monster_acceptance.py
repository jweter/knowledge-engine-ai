from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from knowledge_engine_ai.monster_acceptance import (
    MONSTER_CASE_ID,
    REQUIRED_FACT_FIELDS,
    evaluate_monster_acceptance,
)
from knowledge_engine_ai.monster_acceptance_cli import app
from knowledge_engine_ai.research_case_benchmark import default_golden_research_cases
from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

AI_SHA = "a" * 40
CORE_SHA = "b" * 40
WEB_SHA = "c" * 40
SESSION_ID = "session-monster-1"
PRIVATE_MARKERS = (
    "PRIVATE NARRATIVE TEXT",
    "PRIVATE REPORT PROSE",
    "PRIVATE WORKER SUMMARY",
    "Monster Energy drinks every day",
)


def _case() -> Any:
    return next(c for c in default_golden_research_cases() if c.case_id == MONSTER_CASE_ID)


def _manifest(**overrides: object) -> UnattendedAcceptanceManifest:
    values: dict[str, object] = {
        "ai_sha": AI_SHA,
        "core_sha": CORE_SHA,
        "web_sha": WEB_SHA,
        "core_branch": "main",
        "environment_id": "local-idle-worker",
        "created_at_utc": "2026-09-26T12:00:00+00:00",
        "scenario_id": MONSTER_CASE_ID,
        "ollama_model": "qwen3:8b",
        "ollama_runtime_id": "ollama-0.12.3",
        "requested_checks": ("monster_acceptance",),
    }
    values.update(overrides)
    return UnattendedAcceptanceManifest(**values)  # type: ignore[arg-type]


def _worker_result(manifest: UnattendedAcceptanceManifest, **overrides: object) -> dict[str, Any]:
    request = manifest.core_worker_request()
    result: dict[str, Any] = {
        "request_id": request["request_id"],
        "repository": request["repository"],
        "exact_sha": request["exact_sha"],
        "environment_id": request["environment_id"],
        "status": "PASS",
        "completed_at_utc": "2026-09-26T12:30:00+00:00",
        "summary": "PRIVATE WORKER SUMMARY C:/Users/someone/secret",
    }
    result.update(overrides)
    return result


def _runtime_identity(**overrides: object) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "ai_sha": AI_SHA.upper(),
        "core_sha": CORE_SHA,
        "web_sha": WEB_SHA,
        "ollama_model": "qwen3:8b",
        "ollama_runtime_id": "ollama-0.12.3",
    }
    identity.update(overrides)
    return identity


def _research_result(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": SESSION_ID,
        "question": _case().question,
        "narrative": "PRIVATE NARRATIVE TEXT",
        "narrative_releaseable": True,
        "discovery": {"triggered": True},
    }
    payload.update(overrides)
    return payload


def _research_report(**overrides: object) -> dict[str, Any]:
    case = _case()
    report: dict[str, Any] = {
        "schema_version": 1,
        "question": case.question,
        "bottom_line": "PRIVATE REPORT PROSE",
        "conclusion_rows": [
            {"question_dimension": dimension, "conclusion": "PRIVATE REPORT PROSE"}
            for dimension in case.required_dimensions
        ],
        "degraded_providers": ["crossref"],
        "provider_statuses": [
            {"provider": "pubmed", "attempted": True, "outcome": "success", "reason": None},
            {"provider": "openalex", "attempted": True, "outcome": "ok", "reason": None},
            {"provider": "crossref", "attempted": True, "outcome": "timeout", "reason": "x"},
            {"provider": "arxiv", "attempted": False, "outcome": None, "reason": None},
        ],
        "session_id": SESSION_ID,
    }
    report.update(overrides)
    return report


def _benchmark_facts(**overrides: object) -> dict[str, Any]:
    case = _case()
    facts: dict[str, Any] = {
        "case_id": case.case_id,
        "session_id": SESSION_ID,
        "initial_indexed_evidence_record_count": 0,
        "covered_variants": list(case.required_variants),
        "completed_search_tracks": list(case.required_search_tracks),
        "reviewed_source_ids": list(case.required_seed_source_ids),
        "represented_counterevidence_source_ids": list(case.counterevidence_seed_source_ids),
        "source_fields_audited_source_ids": list(case.required_seed_source_ids),
        "violated_inference_guard_ids": [],
        "direct_long_term_study_found": False,
        "direct_long_term_gap_reported": True,
        "factual_claim_count": 12,
        "source_linked_factual_claim_count": 12,
        "source_field_gaps": [],
    }
    facts.update(overrides)
    return facts


def _evaluate(
    manifest: UnattendedAcceptanceManifest | None = None, **overrides: Any
) -> dict[str, Any]:
    manifest = manifest or _manifest()
    kwargs: dict[str, Any] = {
        "worker_result": _worker_result(manifest),
        "observed_runtime_identity": _runtime_identity(),
        "research_result": _research_result(),
        "research_report": _research_report(),
        "benchmark_facts": _benchmark_facts(),
    }
    kwargs.update(overrides)
    return evaluate_monster_acceptance(manifest, **kwargs).to_dict()


def test_fully_resolved_bound_run_passes_with_exact_identity() -> None:
    evidence = _evaluate()

    assert evidence["status"] == "PASS"
    assert evidence["reason_codes"] == []
    assert evidence["product_reality_verified"] is False
    assert evidence["identity"]["ai_sha"] == AI_SHA
    assert evidence["identity"]["core_sha"] == CORE_SHA
    assert evidence["identity"]["web_sha"] == WEB_SHA
    assert evidence["identity"]["ollama_model"] == "qwen3:8b"
    assert evidence["identity"]["ollama_runtime_id"] == "ollama-0.12.3"
    assert evidence["benchmark"]["passes"] is True


def test_evidence_is_sanitized_of_prose_questions_and_worker_summary() -> None:
    serialized = json.dumps(_evaluate())

    for marker in PRIVATE_MARKERS:
        assert marker not in serialized
    assert "C:/Users" not in serialized


@pytest.mark.parametrize("field", ["ai_sha", "core_sha", "web_sha"])
def test_runtime_sha_mismatch_fails_closed(field: str) -> None:
    evidence = _evaluate(observed_runtime_identity=_runtime_identity(**{field: "d" * 40}))

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == [f"runtime_identity_mismatch:{field}"]
    assert evidence["benchmark"] is None


@pytest.mark.parametrize("field", ["ollama_model", "ollama_runtime_id"])
def test_ollama_identity_mismatch_fails_closed(field: str) -> None:
    evidence = _evaluate(observed_runtime_identity=_runtime_identity(**{field: "other"}))

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == [f"runtime_identity_mismatch:{field}"]


def test_missing_runtime_identity_field_fails_closed() -> None:
    identity = _runtime_identity()
    del identity["web_sha"]

    evidence = _evaluate(observed_runtime_identity=identity)

    assert evidence["reason_codes"] == ["runtime_identity_mismatch:web_sha"]


def test_worker_result_for_other_core_sha_fails_closed() -> None:
    manifest = _manifest()

    evidence = _evaluate(manifest, worker_result=_worker_result(manifest, exact_sha="d" * 40))

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == ["worker_result_identity_mismatch"]


def test_manifest_for_other_scenario_fails_closed() -> None:
    evidence = _evaluate(_manifest(scenario_id="research-report-v1"))

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == ["manifest_scenario_not_monster_case"]


@pytest.mark.parametrize("status", ["ENVIRONMENT_FAILURE", "REVIEW_REQUIRED", "FAIL"])
def test_non_pass_worker_status_is_propagated(status: str) -> None:
    manifest = _manifest()

    evidence = _evaluate(manifest, worker_result=_worker_result(manifest, status=status))

    assert evidence["status"] == status
    assert evidence["reason_codes"] == ["worker_status_not_pass"]


def test_missing_worker_result_is_environment_failure() -> None:
    evidence = _evaluate(worker_result=None)

    assert evidence["status"] == "ENVIRONMENT_FAILURE"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"research_result": None}, "research_result_missing"),
        ({"research_report": None}, "research_report_missing"),
        ({"observed_runtime_identity": None}, "runtime_identity_missing"),
    ],
)
def test_missing_research_artifacts_fail_closed(override: dict[str, Any], reason: str) -> None:
    evidence = _evaluate(**override)

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == [reason]


def test_missing_benchmark_facts_are_unresolved_not_pass() -> None:
    evidence = _evaluate(benchmark_facts=None)

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == ["benchmark_facts_unresolved"]
    assert evidence["unresolved_fact_fields"] == list(REQUIRED_FACT_FIELDS)


def test_unknown_benchmark_fact_is_unresolved_not_pass() -> None:
    evidence = _evaluate(benchmark_facts=_benchmark_facts(reviewed_source_ids=None))

    assert evidence["status"] == "FAIL"
    assert evidence["unresolved_fact_fields"] == ["reviewed_source_ids"]


def test_absent_benchmark_fact_key_is_unresolved_not_pass() -> None:
    facts = _benchmark_facts()
    del facts["direct_long_term_gap_reported"]

    evidence = _evaluate(benchmark_facts=facts)

    assert evidence["status"] == "FAIL"
    assert evidence["unresolved_fact_fields"] == ["direct_long_term_gap_reported"]


def test_facts_cannot_override_report_derived_facts() -> None:
    evidence = _evaluate(
        benchmark_facts=_benchmark_facts(covered_dimensions=list(_case().required_dimensions))
    )

    assert evidence["reason_codes"] == ["benchmark_facts_override_derived_fact"]


def test_facts_bound_to_other_session_fail_closed() -> None:
    evidence = _evaluate(benchmark_facts=_benchmark_facts(session_id="other-session"))

    assert evidence["reason_codes"] == ["benchmark_facts_identity_mismatch"]


def test_report_from_other_session_fails_closed() -> None:
    evidence = _evaluate(research_report=_research_report(session_id="other-session"))

    assert evidence["reason_codes"] == ["research_report_session_mismatch"]


def test_non_golden_question_fails_closed() -> None:
    evidence = _evaluate(research_result=_research_result(question="Is coffee healthy?"))

    assert evidence["reason_codes"] == ["research_question_not_golden_case"]


def test_unreleaseable_research_result_fails_closed() -> None:
    evidence = _evaluate(research_result=_research_result(narrative_releaseable=False))

    assert evidence["reason_codes"] == ["research_result_not_releaseable"]


def test_missing_report_dimension_fails_golden_case() -> None:
    rows = _research_report()["conclusion_rows"][:-1]

    evidence = _evaluate(research_report=_research_report(conclusion_rows=rows))

    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == ["golden_research_case_failed"]
    assert evidence["benchmark"]["missing_dimensions"] == ["certainty_and_missing_evidence"]


def test_unreported_degraded_provider_fails_golden_case() -> None:
    evidence = _evaluate(research_report=_research_report(degraded_providers=[]))

    assert evidence["reason_codes"] == ["golden_research_case_failed"]
    assert evidence["benchmark"]["unreported_degraded_providers"] == ["crossref"]


def test_untriggered_discovery_fails_golden_case() -> None:
    evidence = _evaluate(research_result=_research_result(discovery=None))

    assert evidence["reason_codes"] == ["golden_research_case_failed"]
    assert evidence["benchmark"]["discovery_required_but_not_triggered"] is True


def test_source_field_gap_outside_golden_seeds_is_rejected() -> None:
    facts = _benchmark_facts(
        source_field_gaps=[{"source_id": "PRIVATE REPORT PROSE", "missing_fields": ["dose"]}]
    )

    evidence = _evaluate(benchmark_facts=facts)

    assert evidence["reason_codes"] == ["benchmark_facts_invalid"]


def test_cli_writes_sanitized_evidence_and_fails_on_missing_artifact(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_data = {**manifest.__dict__, "requested_checks": list(manifest.requested_checks)}
    files = {
        "manifest": manifest_data,
        "worker-result": _worker_result(manifest),
        "runtime-identity": _runtime_identity(),
        "research-result": _research_result(),
        "research-report": _research_report(),
    }
    args: list[str] = []
    for name, data in files.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        args += [f"--{name}", str(path)]
    output = tmp_path / "out" / "evidence.json"
    missing_facts = tmp_path / "missing-facts.json"

    result = CliRunner().invoke(
        app, [*args, "--benchmark-facts", str(missing_facts), "--output", str(output)]
    )

    assert result.exit_code == 1
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "FAIL"
    assert evidence["reason_codes"] == ["benchmark_facts_unresolved"]

    missing_facts.write_text(json.dumps(_benchmark_facts()), encoding="utf-8")
    result = CliRunner().invoke(
        app, [*args, "--benchmark-facts", str(missing_facts), "--output", str(output)]
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
