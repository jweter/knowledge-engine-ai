from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine_ai.ke_client import evidence_report


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
    "disclaimer": "retrieval only",
}


class _FakeCompletedProcess:
    returncode = 0
    stdout = json.dumps(_VALID_PAYLOAD)
    stderr = ""


def test_evidence_report_runs_from_explicit_core_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        del command
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess()

    monkeypatch.setattr("knowledge_engine_ai.ke_client.subprocess.run", fake_run)
    core_root = tmp_path / "knowledge-engine-core"

    evidence_report(
        "q",
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        working_directory=core_root,
    )

    assert captured_kwargs["cwd"] == core_root
    assert captured_kwargs.get("shell", False) is False
