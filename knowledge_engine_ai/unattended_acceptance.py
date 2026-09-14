from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

CORE_REPOSITORY = "jweter/knowledge-engine-core"
CORE_RESULT_STATUSES = frozenset(
    {
        "PASS",
        "FAIL",
        "REVIEW_REQUIRED",
        "PRODUCT_REALITY_REQUIRED",
        "ENVIRONMENT_FAILURE",
    }
)


def _normalized_sha(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{field_name} must be a full 40-character hexadecimal commit SHA")
    return normalized


def _required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True)
class UnattendedAcceptanceManifest:
    """AI-side context bound to one Core unattended-worker request.

    The Core `WorkerRequest` / `WorkerResult` contract remains producer authority.
    This manifest adds consumer-side AI/Web/Ollama identity without creating a
    competing worker protocol or persisting private research payloads.
    """

    ai_sha: str
    core_sha: str
    web_sha: str
    core_branch: str
    environment_id: str
    created_at_utc: str
    scenario_id: str
    ollama_model: str
    ollama_runtime_id: str
    requested_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "ai_sha", _normalized_sha(self.ai_sha, field_name="ai_sha"))
        object.__setattr__(self, "core_sha", _normalized_sha(self.core_sha, field_name="core_sha"))
        object.__setattr__(self, "web_sha", _normalized_sha(self.web_sha, field_name="web_sha"))
        for field_name in (
            "core_branch",
            "environment_id",
            "created_at_utc",
            "scenario_id",
            "ollama_model",
            "ollama_runtime_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        checks = tuple(check.strip() for check in self.requested_checks)
        if not checks or any(not check for check in checks):
            raise ValueError("requested_checks must contain at least one non-empty check")
        if len(set(checks)) != len(checks):
            raise ValueError("requested_checks may not contain duplicates")
        object.__setattr__(self, "requested_checks", checks)

    def identity_sha256(self) -> str:
        payload = {
            "ai_sha": self.ai_sha,
            "core_branch": self.core_branch,
            "core_sha": self.core_sha,
            "environment_id": self.environment_id,
            "ollama_model": self.ollama_model,
            "ollama_runtime_id": self.ollama_runtime_id,
            "requested_checks": list(self.requested_checks),
            "scenario_id": self.scenario_id,
            "web_sha": self.web_sha,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    def core_worker_request(self) -> dict[str, object]:
        """Return the exact JSON shape consumed by Core's WorkerRequest model."""

        return {
            "repository": CORE_REPOSITORY,
            "branch": self.core_branch,
            "exact_sha": self.core_sha,
            "request_id": f"ai-{self.identity_sha256()}",
            "requested_checks": list(self.requested_checks),
            "environment_id": self.environment_id,
            "created_at_utc": self.created_at_utc,
        }

    def validate_worker_result(self, result: Mapping[str, Any]) -> str:
        """Fail closed unless a Core result matches this exact unattended run."""

        request = self.core_worker_request()
        required_identity = {
            "request_id": request["request_id"],
            "repository": CORE_REPOSITORY,
            "exact_sha": self.core_sha,
            "environment_id": self.environment_id,
        }
        for key, expected in required_identity.items():
            if result.get(key) != expected:
                raise ValueError(f"worker result {key} does not match the unattended request")

        status = result.get("status")
        if not isinstance(status, str) or status not in CORE_RESULT_STATUSES:
            raise ValueError("worker result status is not allowed by the Core worker contract")

        summary = result.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("worker result summary must be non-empty")

        return status
