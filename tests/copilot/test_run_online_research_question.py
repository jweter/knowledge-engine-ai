"""Regression tests for the opt-in online-evidence Research Report wrapper.

`run_online_research_question` is a thin, independent wrapper beside
`run_research_question` -- see its docstring. These tests stub Core's CLI at the
same `ke_client._run_ke_command` boundary `test_online_research_bridge.py` uses, so
a successful run, a run with failed/unavailable sources, and a hard bridge failure
each exercise the real `online_research_evidence` temporary-directory lifecycle
(not a mocked-away one), and we can assert the temporary root is actually removed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine_ai import ke_client
from knowledge_engine_ai.copilot.research_report import ReportCertainty
from knowledge_engine_ai.copilot.run_research_question import run_online_research_question


def _bundle(*, with_unavailable_source: bool) -> tuple[dict[str, Any], str]:
    content = "The observed effect is limited."
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    quote = "observed effect"
    start = content.index(quote)
    excerpt_hash = hashlib.sha256(f"src1\n{start}\n{quote}".encode()).hexdigest()[:12]
    sources: list[dict[str, Any]] = [
        {
            "source_id": "src1",
            "url": "https://example.org/study",
            "provider": "pubmed",
            "retrieved_at": "2026-11-14T00:00:00+00:00",
            "status": "retrieved",
            "content_sha256": digest,
            "failure_reason": None,
            "title": "Example",
        }
    ]
    if with_unavailable_source:
        sources.append(
            {
                "source_id": "src2",
                "url": "https://example.org/unavailable",
                "provider": "pubmed",
                "retrieved_at": "2026-11-14T00:00:00+00:00",
                "status": "failed",
                "content_sha256": None,
                "failure_reason": "provider unavailable",
                "title": None,
            }
        )
    payload: dict[str, Any] = {
        "schema": "ke-online-evidence/v1",
        "question": "Does X help?",
        "sources": sources,
        "excerpts": [
            {
                "excerpt_id": f"src1#{excerpt_hash}",
                "source_id": "src1",
                "text": quote,
                "char_start": start,
                "char_end": start + len(quote),
            }
        ],
        "claims": [
            {
                "claim_id": "claim1",
                "text": "An effect was observed.",
                "status": "supported",
                "citations": [{"excerpt_id": f"src1#{excerpt_hash}", "stance": "supports"}],
            }
        ],
    }
    return payload, content


def _fake_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_unavailable_source: bool = False,
    retrieval_returncode: int = 0,
) -> list[Path]:
    temporary_roots: list[Path] = []

    def fake_run(
        command: list[str],
        *,
        operation: str,
        execution_budget: Any,
        working_directory: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del operation, working_directory
        assert execution_budget is not None
        if command[1] == "online-research":
            if retrieval_returncode:
                return subprocess.CompletedProcess(
                    command, retrieval_returncode, "", "secret provider response"
                )
            cache = Path(command[command.index("--cache-dir") + 1])
            output = Path(command[command.index("--output") + 1])
            temporary_roots.append(output.parent)
            cache.mkdir(parents=True)
            payload, content = _bundle(with_unavailable_source=with_unavailable_source)
            digest = payload["sources"][0]["content_sha256"]
            (cache / f"{digest}.txt").write_bytes(content.encode("utf-8"))
            output.write_text(json.dumps(payload), encoding="utf-8")
            output.with_name(output.name + ".discovery.json").write_text(
                json.dumps({"search_run_id": "run-online-1", "bundle": output.name}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command[1] == "online-evidence-validate"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ke_client, "_run_ke_command", fake_run)
    monkeypatch.setattr(ke_client, "_resolve_ke_executable", lambda name: name)
    return temporary_roots


def test_successful_bundle_produces_report_and_cleans_up_temp_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _fake_cli(monkeypatch)

    result = run_online_research_question("Does X help?", max_sources=2, providers="pubmed")

    assert result.error_code is None
    assert result.search_run_id == "run-online-1"
    assert result.available
    report = result.report
    assert report is not None
    assert report.question == "Does X help?"
    assert report.session_id == "run-online-1"
    assert len(report.conclusion_rows) == 1
    assert report.conclusion_rows[0].conclusion == "[supported] An effect was observed."
    assert report.conclusion_rows[0].certainty is ReportCertainty.LOW
    assert report.missing_evidence == ()
    assert roots and all(not root.exists() for root in roots)


def test_bundle_with_failed_source_still_produces_report_with_missing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _fake_cli(monkeypatch, with_unavailable_source=True)

    result = run_online_research_question("Does X help?")

    assert result.error_code is None
    report = result.report
    assert report is not None
    assert any("src2 failed" in m for m in report.missing_evidence)
    assert "src2" not in {s for row in report.conclusion_rows for s in row.supporting_evidence_ids}
    assert roots and all(not root.exists() for root in roots)


def test_bridge_failure_returns_stable_error_code_without_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_cli(monkeypatch, retrieval_returncode=3)

    result = run_online_research_question("Does X help?")

    assert result.error_code == "online_research_bridge_failed"
    assert result.report is None
    assert not result.available
    assert result.search_run_id is None


def test_bridge_failure_during_validation_cleans_up_temp_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _fake_cli(monkeypatch)
    original = ke_client._run_ke_command

    def fail_validation(
        command: list[str],
        *,
        operation: str,
        execution_budget: Any,
        working_directory: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if command[1] == "online-evidence-validate":
            return subprocess.CompletedProcess(command, 1, "", "")
        return original(
            command,
            operation=operation,
            execution_budget=execution_budget,
            working_directory=working_directory,
        )

    monkeypatch.setattr(ke_client, "_run_ke_command", fail_validation)
    monkeypatch.setattr(ke_client, "_resolve_ke_executable", lambda name: name)

    result = run_online_research_question("Does X help?")

    assert result.error_code == "online_research_bridge_failed"
    assert result.report is None
    assert roots and all(not root.exists() for root in roots)


def test_invalid_timeout_is_rejected_before_any_core_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        calls.append(list(args))
        raise AssertionError("Core must not be invoked for an invalid time budget.")

    monkeypatch.setattr(ke_client, "_run_ke_command", fail_if_called)

    result = run_online_research_question("Does X help?", timeout_seconds=0)

    assert result.error_code == "online_research_invalid_request"
    assert result.report is None
    assert calls == []
