from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    CONTRADICTION_SIGNAL_PHRASES,
    build_contradiction_query,
    run_parallel_retrieval,
)


def _payload(question: str, evidence_record_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "question": question,
        "sources_path": "sources.csv",
        "evidence_path": "evidence.jsonl",
        "evidence_summary": {
            "total": 1,
            "draft": 0,
            "reviewed": 1,
            "needs_revision": 0,
            "rejected": 0,
            "unspecified": 0,
            "readiness_note": "ready.",
        },
        "papers": [
            {
                "rank": 1,
                "paper_id": 1,
                "title": "T",
                "authors": "A",
                "year": "2026",
                "journal": "J",
                "doi": "10.1/x",
                "source_url": "https://example.org",
                "license_type": "CC BY",
                "metadata_source": "sources.csv",
                "retrieval_score": -1.0,
                "retrieval_snippet": "s",
                "why_matched": "m",
                "citation": "c",
                "evidence_records": [
                    {"evidence_record_id": record_id} for record_id in evidence_record_ids
                ],
            }
        ],
        "disclaimer": "This report is retrieval plus recorded evidence only.",
    }


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _no_intelligence(command: list[str]) -> _FakeCompletedProcess:
    """`evidence-intelligence` always reports "no graph claim found"."""

    return _FakeCompletedProcess(1, "", "No graph claim found for this record.")


def test_build_contradiction_query_appends_the_validated_phrase_set() -> None:
    query = build_contradiction_query("does semaglutide reduce body weight")

    assert query.startswith("does semaglutide reduce body weight ")
    for phrase in CONTRADICTION_SIGNAL_PHRASES:
        assert phrase in query


def test_build_contradiction_query_rejects_an_empty_question() -> None:
    with pytest.raises(ValueError, match="Question must not be empty"):
        build_contradiction_query("   ")


def test_run_parallel_retrieval_runs_both_branches_and_computes_recall_gain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "does semaglutide reduce body weight"
    contradiction_query = build_contradiction_query(question)

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        if command[1] == "evidence-intelligence":
            return _no_intelligence(command)
        assert command[1] == "evidence-report"
        query = command[2]
        if query == question:
            return _FakeCompletedProcess(0, json.dumps(_payload(query, ["ev-1", "ev-2"])))
        assert query == contradiction_query
        return _FakeCompletedProcess(0, json.dumps(_payload(query, ["ev-2", "ev-3"])))

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_parallel_retrieval(
        question, sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl"
    )

    assert result.question == question
    assert result.primary.error is None
    assert result.contradiction.error is None
    assert result.primary_evidence_record_ids == frozenset({"ev-1", "ev-2"})
    assert result.contradiction_evidence_record_ids == frozenset({"ev-2", "ev-3"})
    assert result.contradiction_only_evidence_record_ids == frozenset({"ev-3"})
    assert result.external_discovery_result is None
    assert result.external_discovery_error is None


def test_run_parallel_retrieval_captures_one_branchs_failure_without_losing_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "does semaglutide reduce body weight"

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        if command[1] == "evidence-intelligence":
            return _no_intelligence(command)
        assert command[1] == "evidence-report"
        query = command[2]
        if query == question:
            return _FakeCompletedProcess(0, json.dumps(_payload(query, ["ev-1"])))
        return _FakeCompletedProcess(1, "", "corpus unavailable")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_parallel_retrieval(
        question, sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl"
    )

    assert result.primary.error is None
    assert result.primary.report is not None
    assert result.contradiction.error is not None
    assert result.contradiction.report is None
    assert result.primary_evidence_record_ids == frozenset({"ev-1"})
    assert result.contradiction_evidence_record_ids == frozenset()
    assert result.contradiction_only_evidence_record_ids == frozenset()


def test_run_parallel_retrieval_runs_external_discovery_and_reports_its_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "does semaglutide reduce body weight"

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        if command[1] == "evidence-intelligence":
            return _no_intelligence(command)
        assert command[1] == "evidence-report"
        return _FakeCompletedProcess(0, json.dumps(_payload(command[2], [])))

    monkeypatch.setattr(subprocess, "run", fake_run)

    calls: list[str] = []

    def fake_external(q: str) -> object:
        calls.append(q)
        return {"candidates": 3}

    result = run_parallel_retrieval(
        question,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        external_discovery=fake_external,
    )

    assert calls == [question]
    assert result.external_discovery_result == {"candidates": 3}
    assert result.external_discovery_error is None


def test_run_parallel_retrieval_captures_external_discovery_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "does semaglutide reduce body weight"

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        if command[1] == "evidence-intelligence":
            return _no_intelligence(command)
        assert command[1] == "evidence-report"
        return _FakeCompletedProcess(0, json.dumps(_payload(command[2], [])))

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_external(q: str) -> object:
        raise RuntimeError("external service unreachable")

    result = run_parallel_retrieval(
        question,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        external_discovery=fake_external,
    )

    assert result.external_discovery_result is None
    assert result.external_discovery_error == "external service unreachable"
    # Both retrieval branches still succeed despite the external-discovery failure.
    assert result.primary.error is None
    assert result.contradiction.error is None
