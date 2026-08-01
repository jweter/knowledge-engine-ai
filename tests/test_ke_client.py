from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.ke_client import KeCommandError, evidence_report

_VALID_PAYLOAD = {
    "schema_version": 1,
    "question": "q",
    "sources_path": "sources.csv",
    "evidence_path": "evidence.jsonl",
    "evidence_summary": {
        "total": 0,
        "draft": 0,
        "reviewed": 0,
        "needs_revision": 0,
        "rejected": 0,
        "unspecified": 0,
        "readiness_note": "no records.",
    },
    "papers": [],
    "disclaimer": "This report is retrieval plus recorded evidence only.",
}


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_evidence_report_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"

    report = evidence_report("q", sources=sources, evidence=evidence, limit=7)

    assert report.question == "q"
    assert captured["command"] == [
        "ke",
        "evidence-report",
        "q",
        "--sources",
        str(sources),
        "--evidence",
        str(evidence),
        "--limit",
        "7",
        "--format",
        "json",
    ]


def test_evidence_report_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "No relevant papers found in the indexed corpus.")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="No relevant papers found"):
        evidence_report("q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl")


def test_evidence_report_raises_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, "not json")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="did not return valid JSON"):
        evidence_report("q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl")


def test_evidence_report_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        evidence_report("q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl")


def test_evidence_report_raises_on_an_unparseable_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, json.dumps({"schema_version": 999}))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="Unsupported evidence-report schema_version"):
        evidence_report("q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl")


def test_evidence_report_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(0, json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)

    evidence_report("q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl")

    assert captured_kwargs.get("shell", False) is False
