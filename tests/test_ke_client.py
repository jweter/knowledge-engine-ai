from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.ke_client import (
    KeCommandError,
    enriched_evidence_report,
    evidence_intelligence,
    evidence_report,
)

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

_VALID_INTELLIGENCE_PAYLOAD = {
    "schema_version": 1,
    "evidence_record_id": "ev-1",
    "claim_id": 1,
    "evidence_quality": {
        "score": 94,
        "study_design_tier": "randomized_controlled_trial",
        "manually_reviewed": True,
    },
    "evidence_consensus": {
        "relationship_edge_count": 2,
        "supports_count": 2,
        "contradicts_count": 0,
        "agreement_total": 2,
        "score": 100,
        "reliability": "moderate",
    },
    "claim_confidence": {"score": 89, "reliability": "moderate"},
    "evidence_coverage": {
        "records_in_relationship": 7,
        "total_records": 155,
        "percentage": 5,
    },
    "synthesis": ["Evidence Quality: 94/100."],
    "scope_note": "Every number above is computed deterministically.",
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


def test_evidence_intelligence_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, json.dumps(_VALID_INTELLIGENCE_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)
    evidence = tmp_path / "evidence.jsonl"

    result = evidence_intelligence("ev-1", evidence=evidence)

    assert result is not None
    assert result.evidence_quality.score == 94
    assert result.claim_confidence.score == 89
    assert captured["command"] == [
        "ke",
        "evidence-intelligence",
        "--evidence",
        str(evidence),
        "--evidence-record-id",
        "ev-1",
        "--format",
        "json",
    ]


def test_evidence_intelligence_returns_none_when_record_has_no_graph_claim_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(
            1, "", "No graph claim found for evidence_record_id: ev-1\nRun `ke graph-build`..."
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = evidence_intelligence("ev-1", evidence=tmp_path / "e.jsonl")

    assert result is None


def test_evidence_intelligence_raises_on_a_real_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "No evidence record found for evidence_record_id: ev-1")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="No evidence record found"):
        evidence_intelligence("ev-1", evidence=tmp_path / "e.jsonl")


def test_enriched_evidence_report_attaches_intelligence_to_each_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = dict(_VALID_PAYLOAD)
    payload["papers"] = [
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
            "evidence_records": [{"evidence_record_id": "ev-1"}],
        }
    ]

    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        calls.append(command)
        if command[1] == "evidence-report":
            return _FakeCompletedProcess(0, json.dumps(payload))
        return _FakeCompletedProcess(0, json.dumps(_VALID_INTELLIGENCE_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)

    report = enriched_evidence_report(
        "q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl"
    )

    assert len(calls) == 2
    record = report.papers[0].evidence_records[0]
    assert record.evidence_intelligence is not None
    assert record.evidence_intelligence.evidence_quality.score == 94


def test_enriched_evidence_report_leaves_intelligence_none_without_evidence_record_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = dict(_VALID_PAYLOAD)
    payload["papers"] = [
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
            "evidence_records": [{"evidence_record_id": None}],
        }
    ]

    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        calls.append(command)
        return _FakeCompletedProcess(0, json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", fake_run)

    report = enriched_evidence_report(
        "q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl"
    )

    assert len(calls) == 1
    assert report.papers[0].evidence_records[0].evidence_intelligence is None
