from __future__ import annotations

import pytest

from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

AI_SHA = "a" * 40
CORE_SHA = "b" * 40
WEB_SHA = "c" * 40


def _manifest() -> UnattendedAcceptanceManifest:
    return UnattendedAcceptanceManifest(
        ai_sha=AI_SHA,
        core_sha=CORE_SHA,
        web_sha=WEB_SHA,
        core_branch="main",
        environment_id="jeremy-laptop-idle-worker",
        created_at_utc="2026-09-14T23:30:00+00:00",
        scenario_id="research-report-v1",
        ollama_model="qwen3:8b",
        ollama_runtime_id="ollama-local",
        requested_checks=("preflight", "ollama_health"),
    )


def _valid_result(manifest: UnattendedAcceptanceManifest) -> dict[str, object]:
    request = manifest.core_worker_request()
    return {
        "request_id": request["request_id"],
        "repository": request["repository"],
        "exact_sha": request["exact_sha"],
        "environment_id": request["environment_id"],
        "status": "PASS",
        "completed_at_utc": "2026-09-14T23:31:00+00:00",
        "summary": "Preflight and Ollama health checks passed.",
        "artifact_refs": [],
        "failure_class": None,
    }


def test_manifest_builds_core_worker_request_with_exact_identity() -> None:
    manifest = _manifest()

    request = manifest.core_worker_request()

    assert request == {
        "repository": "jweter/knowledge-engine-core",
        "branch": "main",
        "exact_sha": CORE_SHA,
        "request_id": f"ai-{manifest.identity_sha256()}",
        "requested_checks": ["preflight", "ollama_health"],
        "environment_id": "jeremy-laptop-idle-worker",
        "created_at_utc": "2026-09-14T23:30:00+00:00",
    }


def test_identity_changes_when_cross_repo_or_ollama_identity_changes() -> None:
    baseline = _manifest()
    changed = UnattendedAcceptanceManifest(
        **{
            **baseline.__dict__,
            "web_sha": "d" * 40,
        }
    )

    assert baseline.identity_sha256() != changed.identity_sha256()


def test_identity_changes_for_repeated_request_instance() -> None:
    baseline = _manifest()
    repeated = UnattendedAcceptanceManifest(
        **{
            **baseline.__dict__,
            "created_at_utc": "2026-09-14T23:32:00+00:00",
        }
    )

    assert baseline.identity_sha256() != repeated.identity_sha256()
    assert baseline.core_worker_request()["request_id"] != repeated.core_worker_request()["request_id"]


def test_manifest_rejects_partial_sha() -> None:
    values = {**_manifest().__dict__, "core_sha": "abc123"}

    with pytest.raises(ValueError, match="core_sha must be a full 40-character"):
        UnattendedAcceptanceManifest(**values)


def test_manifest_rejects_duplicate_checks() -> None:
    values = {**_manifest().__dict__, "requested_checks": ("preflight", "preflight")}

    with pytest.raises(ValueError, match="may not contain duplicates"):
        UnattendedAcceptanceManifest(**values)


def test_manifest_rejects_timestamp_without_timezone() -> None:
    values = {**_manifest().__dict__, "created_at_utc": "2026-09-14T23:30:00"}

    with pytest.raises(ValueError, match="created_at_utc must include a timezone offset"):
        UnattendedAcceptanceManifest(**values)


def test_worker_result_accepts_core_contract_status_for_exact_request() -> None:
    manifest = _manifest()

    assert manifest.validate_worker_result(_valid_result(manifest)) == "PASS"


def test_worker_result_rejects_wrong_exact_sha() -> None:
    manifest = _manifest()
    result = _valid_result(manifest)
    result["exact_sha"] = "d" * 40

    with pytest.raises(ValueError, match="exact_sha does not match"):
        manifest.validate_worker_result(result)


def test_worker_result_rejects_stale_completion_time() -> None:
    manifest = _manifest()
    result = _valid_result(manifest)
    result["completed_at_utc"] = "2026-09-14T23:29:59+00:00"

    with pytest.raises(ValueError, match="predates the unattended request"):
        manifest.validate_worker_result(result)


def test_worker_result_rejects_missing_completion_time() -> None:
    manifest = _manifest()
    result = _valid_result(manifest)
    del result["completed_at_utc"]

    with pytest.raises(ValueError, match="completed_at_utc must be a timestamp"):
        manifest.validate_worker_result(result)


def test_worker_result_rejects_unknown_status() -> None:
    manifest = _manifest()
    result = _valid_result(manifest)
    result["status"] = "BUSY"

    with pytest.raises(ValueError, match="status is not allowed"):
        manifest.validate_worker_result(result)
