from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.ke_client import (
    FederatedDiscoveryParseError,
    KeCommandError,
    enriched_evidence_report,
    evidence_intelligence,
    evidence_map_report,
    evidence_report,
    federated_discover,
    parse_federated_discovery_result,
    statistical_verify,
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
        "extraction_tier": "manual",
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


@pytest.fixture(autouse=True)
def _isolate_default_ke_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep command-shape tests independent of a developer's installed core."""

    monkeypatch.setattr(shutil, "which", lambda name: None)


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


def test_evidence_report_uses_the_shared_execution_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(0, json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)

    evidence_report(
        "q",
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        execution_budget=ExecutionBudget.from_timeout(10.0),
    )

    timeout = captured_kwargs["timeout"]
    assert isinstance(timeout, float)
    assert 0 < timeout <= 10.0


def test_evidence_report_sanitizes_a_subprocess_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise subprocess.TimeoutExpired(command, timeout=1.0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="exceeded the configured execution time limit"):
        evidence_report(
            "q",
            sources=tmp_path / "private" / "sources.csv",
            evidence=tmp_path / "private" / "evidence.jsonl",
            execution_budget=ExecutionBudget.from_timeout(10.0),
        )


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


def test_evidence_report_resolves_the_ke_executable_via_shutil_which(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Windows-only regression: Poetry's `ke` entry point is `ke.cmd` there,

    and Windows only auto-appends `.exe` when locating a bare command name
    for a subprocess -- `shutil.which` is what actually finds `ke.cmd`.
    """

    monkeypatch.setattr(
        shutil, "which", lambda name: r"C:\venv\Scripts\ke.cmd" if name == "ke" else None
    )
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)

    evidence_report(
        "q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl", ke_executable="ke"
    )

    assert captured["command"][0] == r"C:\venv\Scripts\ke.cmd"


def test_evidence_report_falls_back_to_the_unresolved_name_when_which_finds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(subprocess, "run", fake_run)

    evidence_report(
        "q", sources=tmp_path / "s.csv", evidence=tmp_path / "e.jsonl", ke_executable="ke"
    )

    assert captured["command"][0] == "ke"


def test_evidence_map_report_runs_the_expected_command_and_returns_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, "# Evidence Map Report\n\n...")

    monkeypatch.setattr(subprocess, "run", fake_run)
    map_path = tmp_path / "map.json"
    evidence = tmp_path / "e.jsonl"
    relationships = tmp_path / "rel.jsonl"
    sources = tmp_path / "s.csv"

    report = evidence_map_report(
        map_path, evidence=evidence, relationships=relationships, sources=sources
    )

    assert report == "# Evidence Map Report\n\n..."
    assert captured["command"] == [
        "ke",
        "evidence-map-report",
        str(map_path),
        "--evidence",
        str(evidence),
        "--relationships",
        str(relationships),
        "--sources",
        str(sources),
    ]


def test_evidence_map_report_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "Evidence map report failed; map validation failed.")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="map validation failed"):
        evidence_map_report(
            tmp_path / "map.json",
            evidence=tmp_path / "e.jsonl",
            relationships=tmp_path / "rel.jsonl",
            sources=tmp_path / "s.csv",
        )


def test_statistical_verify_runs_the_expected_command_without_binary_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, "# Statistical Verification\n\n...")

    monkeypatch.setattr(subprocess, "run", fake_run)
    inputs_path = tmp_path / "stats.jsonl"
    evidence = tmp_path / "e.jsonl"

    report = statistical_verify(inputs_path, evidence=evidence)

    assert report == "# Statistical Verification\n\n..."
    assert captured["command"] == [
        "ke",
        "statistical-verify",
        str(inputs_path),
        "--evidence",
        str(evidence),
    ]


def test_statistical_verify_includes_binary_inputs_flag_when_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(0, "# Statistical Verification\n\n...")

    monkeypatch.setattr(subprocess, "run", fake_run)
    inputs_path = tmp_path / "stats.jsonl"
    evidence = tmp_path / "e.jsonl"
    binary_inputs = tmp_path / "binary.jsonl"

    statistical_verify(inputs_path, evidence=evidence, binary_inputs=binary_inputs)

    assert captured["command"] == [
        "ke",
        "statistical-verify",
        str(inputs_path),
        "--evidence",
        str(evidence),
        "--binary-inputs",
        str(binary_inputs),
    ]


def test_statistical_verify_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        statistical_verify(tmp_path / "stats.jsonl", evidence=tmp_path / "e.jsonl")


_VALID_FEDERATED_DISCOVERY_PAYLOAD = {
    "search_run_id": "11111111-1111-1111-1111-111111111111",
    "query": {"text": "semaglutide weight loss", "year_from": None, "year_to": None},
    "completeness": "partial",
    "failed_providers": ["crossref"],
    "provider_statuses": [
        {
            "provider": "pubmed",
            "outcome": "success",
            "attempted": True,
            "result_count": 1,
            "latency_ms": None,
            "reason": None,
        },
        {
            "provider": "crossref",
            "outcome": "failed",
            "attempted": True,
            "result_count": 0,
            "latency_ms": None,
            "reason": "unsupported_query",
        },
    ],
    "candidates": [
        {
            "canonical_id": "doi:10.1000/example",
            "title": "A semaglutide trial",
            "doi": "10.1000/example",
            "publication_year": 2026,
            "observations": [{"provider": "pubmed"}],
        }
    ],
}


def test_parse_federated_discovery_result_parses_a_valid_payload() -> None:
    result = parse_federated_discovery_result(_VALID_FEDERATED_DISCOVERY_PAYLOAD)

    assert result.search_run_id == "11111111-1111-1111-1111-111111111111"
    assert result.query_text == "semaglutide weight loss"
    assert result.completeness == "partial"
    assert result.provider_statuses[0].provider == "pubmed"
    assert result.provider_statuses[1].reason == "unsupported_query"
    assert result.candidates[0].title == "A semaglutide trial"
    assert result.candidates[0].providers == ("pubmed",)


def test_parse_federated_discovery_result_raises_on_a_missing_field() -> None:
    payload = {k: v for k, v in _VALID_FEDERATED_DISCOVERY_PAYLOAD.items() if k != "completeness"}

    with pytest.raises(FederatedDiscoveryParseError, match="missing a required field"):
        parse_federated_discovery_result(payload)


def test_federated_discover_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_DISCOVERY_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger_root = tmp_path / "ledger"

    result = federated_discover(
        "semaglutide weight loss",
        ledger_root=ledger_root,
        limit=5,
        providers=("pubmed", "crossref"),
        openalex_api_key="key-1",
        semantic_scholar_api_key="key-2",
    )

    assert result.search_run_id == "11111111-1111-1111-1111-111111111111"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:6] == [
        "ke",
        "federated-discover",
        "--query",
        "semaglutide weight loss",
        "--ledger-root",
        str(ledger_root),
    ]
    assert "--limit" in command and command[command.index("--limit") + 1] == "5"
    assert (
        "--providers" in command and command[command.index("--providers") + 1] == "pubmed,crossref"
    )
    assert "--openalex-api-key" in command
    assert "--semantic-scholar-api-key" in command
    assert "--output" in command


def test_federated_discover_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="exited 1"):
        federated_discover("q", ledger_root=tmp_path / "ledger")


def test_federated_discover_raises_when_the_output_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="did not write a readable JSON output file"):
        federated_discover("q", ledger_root=tmp_path / "ledger")


def test_federated_discover_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        federated_discover("q", ledger_root=tmp_path / "ledger")


def test_federated_discover_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_DISCOVERY_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    federated_discover("q", ledger_root=tmp_path / "ledger")

    assert captured_kwargs.get("shell", False) is False
