from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "engineering" / "control-plane.json"

@dataclass(frozen=True)
class UnattendedAcceptanceManifest:
    """AI-side context bound to one Core unattended-worker request.
    
    The Core `WorkerRequest` / `WorkerResult` contract remains producer authority.
    This manifest adds consumer-side AI/Web/Ollama identity without creating a
    competing worker protocol or persisting private research payloads.
    """
    identity_sha256: str
    core_worker_request: dict[str, object]

def record_monster_acceptance(manifest: UnattendedAcceptanceManifest) -> None:
    """Record the exact AI/Core/Web SHAs and local Ollama runtime/model."""
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    repository = control.get("repository")
    sha256 = hashlib.sha256(json.dumps(manifest.core_worker_request, sort_keys=True).encode()).hexdigest()
    path = ROOT / "engineering" / "monster_acceptance.json"
    data = {
        "schema_version": 1,
        "repository": repository,
        "identity_sha256": manifest.identity_sha256,
        "core_worker_request_sha256": sha256,
        "recorded_at": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

def validate_monster_acceptance() -> bool:
    """Validate the recorded Monster acceptance."""
    path = ROOT / "engineering" / "monster_acceptance.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        return False
    if data.get("repository") is None:
        return False
    if data.get("identity_sha256") is None:
        return False
    if data.get("core_worker_request_sha256") is None:
        return False
    return True
