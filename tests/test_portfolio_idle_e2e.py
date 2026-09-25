from __future__ import annotations

import json
import subprocess
import sys


def test_portfolio_idle_e2e_emits_exact_head_worker_request() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/portfolio_idle_e2e.py",
            "--ai-sha",
            "a" * 40,
            "--core-sha",
            "b" * 40,
            "--web-sha",
            "c" * 40,
            "--environment-id",
            "idle-worker",
            "--created-at-utc",
            "2026-09-25T14:00:00+00:00",
            "--ollama-model",
            "llama3.1:8b",
            "--ollama-runtime-id",
            "ollama-local",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ai_sha"] == "a" * 40
    assert payload["web_sha"] == "c" * 40
    assert payload["scenario_id"] == "monster-energy-bp-one-year"
    request = payload["core_worker_request"]
    assert request["exact_sha"] == "b" * 40
    assert request["requested_checks"] == [
        "preflight",
        "ollama_health",
        "research_report_v1",
    ]
    assert request["request_id"].startswith("ai-")
