"""Deterministic Core CLI bridge tests: no network, corpus, or Ollama."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine_ai import ke_client
from knowledge_engine_ai.ke_client import KeCommandError, online_research_evidence


def _bundle() -> tuple[dict[str, Any], str]:
    content = "The observed effect is limited."
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    quote = "observed effect"
    start = content.index(quote)
    excerpt_hash = hashlib.sha256(f"src1\n{start}\n{quote}".encode()).hexdigest()[:12]
    payload: dict[str, Any] = {
        "schema": "ke-online-evidence/v1",
        "question": "What is the evidence?",
        "sources": [
            {
                "source_id": "src1",
                "url": "https://example.org/study",
                "provider": "pubmed",
                "retrieved_at": "2026-11-02T12:00:00+00:00",
                "status": "retrieved",
                "content_sha256": digest,
                "failure_reason": None,
                "title": "Example",
            },
            {
                "source_id": "src2",
                "url": "https://example.org/unavailable",
                "provider": "pubmed",
                "retrieved_at": "2026-11-02T12:00:00+00:00",
                "status": "failed",
                "content_sha256": None,
                "failure_reason": "provider unavailable",
                "title": None,
            },
        ],
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
    mutate: Any = None,
    retrieval_returncode: int = 0,
    validation_returncode: int = 0,
    missing: bool = False,
) -> tuple[list[list[str]], list[Path]]:
    calls: list[list[str]] = []
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
        calls.append(command)
        if missing:
            raise FileNotFoundError("secret local installation path")
        if command[1] == "online-research":
            if retrieval_returncode:
                return subprocess.CompletedProcess(
                    command, retrieval_returncode, "", "secret provider response"
                )
            cache = Path(command[command.index("--cache-dir") + 1])
            output = Path(command[command.index("--output") + 1])
            temporary_roots.append(output.parent)
            cache.mkdir(parents=True)
            payload, content = _bundle()
            if mutate is not None:
                mutate(payload)
            digest = _bundle()[0]["sources"][0]["content_sha256"]
            (cache / f"{digest}.txt").write_bytes(content.encode("utf-8"))
            output.write_text(json.dumps(payload), encoding="utf-8")
            output.with_name(output.name + ".discovery.json").write_text(
                json.dumps({"search_run_id": "run-123", "bundle": output.name}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command[1] == "online-evidence-validate"
        return subprocess.CompletedProcess(command, validation_returncode, "", "")

    monkeypatch.setattr(ke_client, "_run_ke_command", fake_run)
    monkeypatch.setattr(ke_client, "_resolve_ke_executable", lambda name: name)
    return calls, temporary_roots


def test_opt_in_cli_bridge_preserves_evidence_and_cleans_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, roots = _fake_cli(monkeypatch)
    result = online_research_evidence("What is the evidence?", providers="pubmed", max_sources=2)
    assert result.search_run_id == "run-123"
    assert len(result.evidence.sources) == 2
    assert result.evidence.sources[1].status == "failed"
    assert result.evidence.sources[1].failure_reason == "provider unavailable"
    assert result.evidence.excerpts[0].text == "observed effect"
    assert result.evidence.claims[0].status == "supported"
    assert [call[1] for call in calls] == ["online-research", "online-evidence-validate"]
    assert calls[0][calls[0].index("--providers") + 1] == "pubmed"
    assert calls[0][calls[0].index("--max-sources") + 1] == "2"
    assert "--contents-dir" in calls[1]
    assert all(not root.exists() for root in roots)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["sources"][0].update(content_sha256="0" * 64),
        lambda payload: payload["excerpts"][0].update(char_end=1000),
        lambda payload: payload["sources"][0].update(content_sha256="../escape"),
        lambda payload: payload["claims"][0].update(status="contradicted"),
    ],
)
def test_invalid_evidence_fails_closed_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    _, roots = _fake_cli(monkeypatch, mutate=mutation)
    with pytest.raises(KeCommandError, match="content verification"):
        online_research_evidence("What is the evidence?")
    assert all(not root.exists() for root in roots)


def test_retrieval_failure_never_leaks_provider_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _fake_cli(monkeypatch, retrieval_returncode=3)
    with pytest.raises(KeCommandError, match="no evidence was accepted") as exc:
        online_research_evidence("Question")
    assert "secret" not in str(exc.value)
    assert len(calls) == 1


def test_validator_failure_is_not_treated_as_valid_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, roots = _fake_cli(monkeypatch, validation_returncode=1)
    with pytest.raises(KeCommandError, match="Core rejected"):
        online_research_evidence("Question")
    assert all(not root.exists() for root in roots)


def test_missing_cli_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_cli(monkeypatch, missing=True)
    with pytest.raises(KeCommandError, match="CLI is unavailable") as exc:
        online_research_evidence("Question")
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("question,max_sources", [("", 3), ("valid", 0), ("valid", 11)])
def test_invalid_request_rejected_before_execution(
    monkeypatch: pytest.MonkeyPatch, question: str, max_sources: int
) -> None:
    calls, _ = _fake_cli(monkeypatch)
    with pytest.raises(KeCommandError):
        online_research_evidence(question, max_sources=max_sources)
    assert calls == []


def test_validation_timeout_cleans_temporary_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, roots = _fake_cli(monkeypatch)
    original = ke_client._run_ke_command

    def timeout_during_validation(
        command: list[str],
        *,
        operation: str,
        execution_budget: Any,
        working_directory: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if command[1] == "online-evidence-validate":
            raise KeCommandError("Core evidence validation exceeded the configured time limit.")
        return original(
            command,
            operation=operation,
            execution_budget=execution_budget,
            working_directory=working_directory,
        )

    monkeypatch.setattr(ke_client, "_run_ke_command", timeout_during_validation)
    with pytest.raises(KeCommandError, match="time limit"):
        online_research_evidence("Question")
    assert all(not root.exists() for root in roots)


def test_malformed_discovery_receipt_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, roots = _fake_cli(monkeypatch)
    original = ke_client._run_ke_command

    def damage_discovery(
        command: list[str],
        *,
        operation: str,
        execution_budget: Any,
        working_directory: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = original(
            command,
            operation=operation,
            execution_budget=execution_budget,
            working_directory=working_directory,
        )
        if command[1] == "online-research":
            output = Path(command[command.index("--output") + 1])
            output.with_name(output.name + ".discovery.json").write_text(
                '{"search_run_id": "", "bundle": "other.json"}', encoding="utf-8"
            )
        return result

    monkeypatch.setattr(ke_client, "_run_ke_command", damage_discovery)
    with pytest.raises(KeCommandError, match="content verification"):
        online_research_evidence("Question")
    assert all(not root.exists() for root in roots)
