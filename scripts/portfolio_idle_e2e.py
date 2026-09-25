from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an exact-head Knowledge Engine unattended acceptance request."
    )
    parser.add_argument("--ai-sha", required=True)
    parser.add_argument("--core-sha", required=True)
    parser.add_argument("--web-sha", required=True)
    parser.add_argument("--core-branch", default="main")
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--created-at-utc", required=True)
    parser.add_argument("--scenario-id", default="monster-energy-bp-one-year")
    parser.add_argument("--ollama-model", required=True)
    parser.add_argument("--ollama-runtime-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = UnattendedAcceptanceManifest(
        ai_sha=args.ai_sha,
        core_sha=args.core_sha,
        web_sha=args.web_sha,
        core_branch=args.core_branch,
        environment_id=args.environment_id,
        created_at_utc=args.created_at_utc,
        scenario_id=args.scenario_id,
        ollama_model=args.ollama_model,
        ollama_runtime_id=args.ollama_runtime_id,
        requested_checks=("preflight", "ollama_health", "research_report_v1"),
    )
    payload = {
        "schema_version": 1,
        "manifest_identity_sha256": manifest.identity_sha256(),
        "scenario_id": manifest.scenario_id,
        "ai_sha": manifest.ai_sha,
        "web_sha": manifest.web_sha,
        "ollama_model": manifest.ollama_model,
        "ollama_runtime_id": manifest.ollama_runtime_id,
        "core_worker_request": manifest.core_worker_request(),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
