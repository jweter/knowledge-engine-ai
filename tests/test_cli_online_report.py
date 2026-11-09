from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from knowledge_engine_ai import cli, ke_client
from knowledge_engine_ai.cli import app
from knowledge_engine_ai.copilot.online_evidence_adapter import (
    ContentCheckedOnlineEvidence,
    OnlineCitation,
    OnlineClaim,
    OnlineExcerpt,
    OnlineSource,
)
from knowledge_engine_ai.ke_client import KeCommandError, OnlineResearchEvidenceResult

SHA = "a" * 64


def _evidence(
    claims: tuple[OnlineClaim, ...], sources: tuple[OnlineSource, ...]
) -> ContentCheckedOnlineEvidence:
    return ContentCheckedOnlineEvidence(
        "Does X help?",
        sources,
        (OnlineExcerpt("s1#1", "s1", "text", None, None),) if sources else (),
        claims,
    )


def _source() -> OnlineSource:
    return OnlineSource(
        "s1", "https://e.org/1", "pubmed", "2026-01-01T00:00:00+00:00",
        "retrieved", SHA, None, None,
    )  # fmt: skip


def _claim() -> OnlineClaim:
    return OnlineClaim("c1", "X helps.", "supported", (OnlineCitation("s1#1", "supports"),))


def _stub(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(question: str, **kwargs: Any) -> OnlineResearchEvidenceResult:
        calls.append({"question": question, **kwargs})
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, OnlineResearchEvidenceResult)
        return result

    monkeypatch.setattr(cli, "online_research_evidence", fake)
    return calls


def test_single_invocation_emits_report_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(
        monkeypatch,
        OnlineResearchEvidenceResult(_evidence((_claim(),), (_source(),)), "run-1"),
    )
    result = CliRunner().invoke(
        app, ["online-report", "Does X help?", "--max-sources", "2", "--providers", "pubmed"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["question"] == "Does X help?"
    assert payload["session_id"] == "run-1"
    assert payload["conclusion_rows"][0]["conclusion"] == "[supported] X helps."
    assert calls[0]["max_sources"] == 2 and calls[0]["providers"] == "pubmed"
    assert calls[0]["execution_budget"] is not None


def test_empty_bundle_is_explicit_insufficient_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, OnlineResearchEvidenceResult(_evidence((), ()), "run-2"))
    result = CliRunner().invoke(app, ["online-report", "Q?"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["research_state"] == "insufficient_evidence"
    assert payload["conclusion_rows"] == []
    assert any("no claims" in m for m in payload["missing_evidence"])


@pytest.mark.parametrize(
    "message",
    [
        "Core online-research failed; no evidence was accepted.",
        "`ke online-research` exceeded the configured execution time limit.",
    ],
)
def test_bridge_failure_and_over_budget_are_errors_without_report(
    monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    _stub(monkeypatch, KeCommandError(message))
    result = CliRunner().invoke(app, ["online-report", "Q?"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert message in result.stderr


def test_real_bridge_over_budget_and_temp_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    roots: list[Path] = []

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        roots.append(Path(command[command.index("--output") + 1]).parent)
        raise KeCommandError("`ke online-research` exceeded the configured execution time limit.")

    monkeypatch.setattr(ke_client, "_run_ke_command", fake_run)
    monkeypatch.setattr(ke_client, "_resolve_ke_executable", lambda name: name)
    result = CliRunner().invoke(app, ["online-report", "Q?"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert roots and not roots[0].exists()


def test_invalid_time_budget_rejected_by_cli() -> None:
    result = CliRunner().invoke(app, ["online-report", "Q?", "--timeout-seconds", "0"])
    assert result.exit_code != 0
