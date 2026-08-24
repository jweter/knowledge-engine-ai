from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.ke_client import (
    CitationSnowballParseError,
    FederatedCoverageReportParseError,
    FederatedDiscoverHistoryParseError,
    FederatedDiscoveryParseError,
    FederatedProviderObservationFlags,
    GeneralQuestionAcquisitionParseError,
    GeneralQuestionPmcPersistenceParseError,
    KeCommandError,
    citation_snowball,
    enriched_evidence_report,
    evidence_intelligence,
    evidence_map_report,
    evidence_report,
    federated_coverage_report,
    federated_discover,
    federated_discover_history,
    general_question_acquire_pmc,
    general_question_acquisition_plan,
    parse_citation_snowball_result,
    parse_federated_coverage_report_result,
    parse_federated_discover_history_result,
    parse_federated_discovery_result,
    parse_general_question_acquisition_plan_result,
    parse_general_question_pmc_persistence_result,
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


def test_parse_federated_discovery_result_defaults_observation_flags_to_none_when_absent() -> None:
    """An older Core run (or a provider that never reports these fields) must not crash.

    `_VALID_FEDERATED_DISCOVERY_PAYLOAD`'s one observation is exactly this
    shape -- `{"provider": "pubmed"}` with no `retracted`/`preprint` keys at
    all. Each field parses to explicit `None`, distinct from the provider
    having asserted `False`.
    """

    result = parse_federated_discovery_result(_VALID_FEDERATED_DISCOVERY_PAYLOAD)

    flags = result.candidates[0].observation_flags
    assert flags == (
        FederatedProviderObservationFlags(
            provider="pubmed", retracted=None, preprint=None, preprint_version=None
        ),
    )


def test_parse_federated_discovery_result_preserves_per_provider_retraction_flags() -> None:
    payload = {
        **_VALID_FEDERATED_DISCOVERY_PAYLOAD,
        "candidates": [
            {
                "canonical_id": "doi:10.1000/example",
                "title": "A semaglutide trial",
                "doi": "10.1000/example",
                "publication_year": 2026,
                "observations": [
                    {"provider": "pubmed", "retracted": True, "preprint": False},
                    {
                        "provider": "arxiv",
                        "retracted": False,
                        "preprint": True,
                        "preprint_version": 2,
                    },
                    {"provider": "crossref"},
                ],
            }
        ],
    }

    result = parse_federated_discovery_result(payload)

    flags = {flag.provider: flag for flag in result.candidates[0].observation_flags}
    assert flags["pubmed"] == FederatedProviderObservationFlags(
        provider="pubmed", retracted=True, preprint=False, preprint_version=None
    )
    assert flags["arxiv"] == FederatedProviderObservationFlags(
        provider="arxiv", retracted=False, preprint=True, preprint_version=2
    )
    # A provider that never reports the flags degrades to None, not a guessed False.
    assert flags["crossref"] == FederatedProviderObservationFlags(
        provider="crossref", retracted=None, preprint=None, preprint_version=None
    )
    # The pre-existing, provider-name-only summary field is unaffected.
    assert result.candidates[0].providers == ("arxiv", "crossref", "pubmed")


def test_parse_federated_discovery_result_preserves_independent_publication_status_flags() -> None:
    """Core's four publication-status flags are independent, not one status enum.

    A Crossref-sourced candidate can carry more than one at once (a work that
    was corrected and later retracted), and a provider asserting one says
    nothing about the others -- so an unreported flag stays `None`, never a
    guessed `False`.
    """

    payload = {
        **_VALID_FEDERATED_DISCOVERY_PAYLOAD,
        "candidates": [
            {
                "canonical_id": "doi:10.1000/example",
                "title": "A semaglutide trial",
                "doi": "10.1000/example",
                "publication_year": 2026,
                "observations": [
                    {
                        "provider": "crossref",
                        "retracted": True,
                        "corrected": True,
                        "expression_of_concern": True,
                        "withdrawn": True,
                    },
                    {"provider": "openalex", "retracted": False},
                ],
            }
        ],
    }

    result = parse_federated_discovery_result(payload)

    flags = {flag.provider: flag for flag in result.candidates[0].observation_flags}
    assert flags["crossref"] == FederatedProviderObservationFlags(
        provider="crossref",
        retracted=True,
        preprint=None,
        preprint_version=None,
        corrected=True,
        expression_of_concern=True,
        withdrawn=True,
    )
    # OpenAlex reports only `is_retracted`; the other three stay unknown.
    assert flags["openalex"] == FederatedProviderObservationFlags(
        provider="openalex",
        retracted=False,
        preprint=None,
        preprint_version=None,
        corrected=None,
        expression_of_concern=None,
        withdrawn=None,
    )


def test_parse_federated_discovery_result_defaults_new_status_flags_to_none_when_absent() -> None:
    """A Core run predating the three newer flags must parse them as unknown."""

    flags = (
        parse_federated_discovery_result(_VALID_FEDERATED_DISCOVERY_PAYLOAD)
        .candidates[0]
        .observation_flags
    )

    assert flags[0].corrected is None
    assert flags[0].expression_of_concern is None
    assert flags[0].withdrawn is None


def test_parse_federated_discovery_result_parses_search_run_created_at_from_coverage() -> None:
    """Core's public `coverage` block carries the search run's own timestamp.

    `docs/core_interface_contract.md` documents `coverage.created_at` as part
    of `ke federated-discover --output`'s public shape (see
    `federated_result_snapshot.build_public_federated_result_payload`, which
    always attaches a `coverage` block from Core's `SearchCoverageReport`).
    """

    payload = {
        **_VALID_FEDERATED_DISCOVERY_PAYLOAD,
        "coverage": {
            "search_run_id": "11111111-1111-1111-1111-111111111111",
            "created_at": "2026-08-15T11:22:00+00:00",
            "query_text": "semaglutide weight loss",
            "year_from": None,
            "year_to": None,
            "limit_per_provider": 20,
            "completeness": "partial",
            "candidate_count": 1,
            "providers_requested": ["pubmed", "crossref"],
            "providers_attempted": ["pubmed", "crossref"],
            "providers_completed": ["pubmed"],
            "providers_failed": ["crossref"],
        },
    }

    result = parse_federated_discovery_result(payload)

    assert result.search_run_created_at == "2026-08-15T11:22:00+00:00"


def test_parse_federated_discovery_result_defaults_search_run_created_at_to_none_when_absent() -> (
    None
):
    """An older payload that predates the `coverage` block must not crash.

    `_VALID_FEDERATED_DISCOVERY_PAYLOAD` has no `coverage` key at all --
    matching the same "absent is not negative" contract already established
    for `provider_disagreements` and per-provider observation flags.
    """

    result = parse_federated_discovery_result(_VALID_FEDERATED_DISCOVERY_PAYLOAD)

    assert result.search_run_created_at is None


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


def test_federated_discover_forwards_project_id_and_research_question_id_when_supplied(
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

    federated_discover(
        "q",
        ledger_root=tmp_path / "ledger",
        project_id="proj-1",
        research_question_id="rq-1",
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--project-id" in command and command[command.index("--project-id") + 1] == "proj-1"
    assert (
        "--research-question-id" in command
        and command[command.index("--research-question-id") + 1] == "rq-1"
    )


def test_federated_discover_omits_project_id_and_research_question_id_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting both flags preserves every existing caller's behavior exactly."""

    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_DISCOVERY_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    federated_discover("q", ledger_root=tmp_path / "ledger")

    command = captured["command"]
    assert isinstance(command, list)
    assert "--project-id" not in command
    assert "--research-question-id" not in command


_VALID_FEDERATED_DISCOVER_HISTORY_PAYLOAD = {
    "research_question_id": "rq-1",
    "run_count": 2,
    "runs": [
        {
            "search_run_id": "33333333-3333-3333-3333-333333333333",
            "created_at": "2026-08-19T09:14:00+00:00",
            "query_text": "semaglutide weight loss",
            "year_from": None,
            "year_to": None,
            "limit_per_provider": 20,
            "completeness": "complete",
            "candidate_count": 5,
            "providers_requested": ["pubmed", "crossref"],
            "providers_attempted": ["pubmed", "crossref"],
            "providers_completed": ["pubmed", "crossref"],
            "providers_failed": [],
        },
        {
            "search_run_id": "44444444-4444-4444-4444-444444444444",
            "created_at": "2026-06-01T08:00:00+00:00",
            "query_text": "semaglutide weight loss",
            "year_from": None,
            "year_to": None,
            "limit_per_provider": 20,
            "completeness": "partial",
            "candidate_count": 1,
            "providers_requested": ["pubmed", "crossref"],
            "providers_attempted": ["pubmed", "crossref"],
            "providers_completed": ["pubmed"],
            "providers_failed": ["crossref"],
        },
    ],
}


def test_parse_federated_discover_history_result_parses_a_valid_payload() -> None:
    result = parse_federated_discover_history_result(_VALID_FEDERATED_DISCOVER_HISTORY_PAYLOAD)

    assert result.research_question_id == "rq-1"
    assert result.run_count == 2
    assert len(result.runs) == 2
    assert result.runs[0].search_run_id == "33333333-3333-3333-3333-333333333333"
    assert result.runs[0].completeness == "complete"
    assert result.runs[0].providers_failed == ()
    assert result.runs[1].providers_failed == ("crossref",)


def test_parse_federated_discover_history_result_handles_no_matching_runs() -> None:
    """A tracked question with no prior recorded search is an honest, non-error state."""

    payload = {"research_question_id": "rq-unseen", "run_count": 0, "runs": []}

    result = parse_federated_discover_history_result(payload)

    assert result.run_count == 0
    assert result.runs == ()


def test_parse_federated_discover_history_result_raises_on_a_missing_field() -> None:
    payload = {k: v for k, v in _VALID_FEDERATED_DISCOVER_HISTORY_PAYLOAD.items() if k != "runs"}

    with pytest.raises(FederatedDiscoverHistoryParseError, match="missing a required field"):
        parse_federated_discover_history_result(payload)


def test_parse_federated_discover_history_result_raises_on_a_malformed_run() -> None:
    payload = {
        "research_question_id": "rq-1",
        "run_count": 1,
        "runs": [{"search_run_id": "only-one-field"}],
    }

    with pytest.raises(FederatedDiscoverHistoryParseError, match="malformed run record"):
        parse_federated_discover_history_result(payload)


def test_federated_discover_history_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_DISCOVER_HISTORY_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger_root = tmp_path / "ledger"

    result = federated_discover_history("rq-1", ledger_root=ledger_root)

    assert result.research_question_id == "rq-1"
    assert result.run_count == 2
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:3] == ["ke", "federated-discover-history", "rq-1"]
    assert "--ledger-root" in command and command[command.index("--ledger-root") + 1] == str(
        ledger_root
    )
    assert "--output" in command


def test_federated_discover_history_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="exited 1"):
        federated_discover_history("rq-1", ledger_root=tmp_path / "ledger")


def test_federated_discover_history_raises_when_the_output_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="did not write a readable JSON output file"):
        federated_discover_history("rq-1", ledger_root=tmp_path / "ledger")


def test_federated_discover_history_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        federated_discover_history("rq-1", ledger_root=tmp_path / "ledger")


def test_federated_discover_history_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_DISCOVER_HISTORY_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    federated_discover_history("rq-1", ledger_root=tmp_path / "ledger")

    assert captured_kwargs.get("shell", False) is False


_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD = {
    "search_run_id": "33333333-3333-3333-3333-333333333333",
    "coverage": {
        "search_run_id": "33333333-3333-3333-3333-333333333333",
        "created_at": "2026-08-19T09:14:00+00:00",
        "query_text": "semaglutide weight loss",
        "year_from": None,
        "year_to": None,
        "limit_per_provider": 20,
        "completeness": "complete",
        "candidate_count": 1,
        "providers_requested": ["alpha"],
        "providers_attempted": ["alpha"],
        "providers_completed": ["alpha"],
        "providers_failed": [],
    },
    "candidates": [
        {
            "canonical_id": "canon-1",
            "title": "A paper found by alpha",
            "doi": "10.1000/alpha-1",
            "publication_year": 2024,
            "observations": [
                {
                    "provider": "alpha",
                    "provider_id": "alpha-1",
                    "title": "A paper found by alpha",
                    "authors": ["A. Author"],
                    "publication_year": 2024,
                    "venue": "Journal of Alpha",
                    "abstract": "An abstract.",
                    "doi": "10.1000/alpha-1",
                    "pmid": None,
                    "pmcid": None,
                    "arxiv_id": None,
                    "openalex_id": None,
                    "semantic_scholar_id": None,
                    "landing_url": "https://example.org/alpha-1",
                    "full_text_url": None,
                    "xml_url": None,
                    "license": None,
                    "metadata_source": "alpha",
                    "pmcid_source": None,
                    "open_access_source": None,
                    "citation_count": 3,
                    "open_access": True,
                    "retracted": False,
                    "preprint": False,
                    "preprint_version": None,
                    "related_journal_doi": None,
                    "related_journal_reference": None,
                    "retrieved_at": "2026-08-19T09:14:00+00:00",
                }
            ],
        }
    ],
}


def test_parse_federated_coverage_report_result_parses_a_valid_payload() -> None:
    result = parse_federated_coverage_report_result(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD)

    assert result.search_run_id == "33333333-3333-3333-3333-333333333333"
    assert result.coverage.completeness == "complete"
    assert result.coverage.candidate_count == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.canonical_id == "canon-1"
    assert candidate.doi == "10.1000/alpha-1"
    assert len(candidate.observations) == 1
    observation = candidate.observations[0]
    assert observation.provider == "alpha"
    assert observation.authors == ("A. Author",)
    assert observation.citation_count == 3
    assert observation.open_access is True


def test_parse_federated_coverage_report_result_preserves_publication_status_flags() -> None:
    """The persisted observation shape mirrors Core's record field for field.

    Core's `CandidateObservationRecord` gained `corrected`/
    `expression_of_concern`/`withdrawn` alongside the existing `retracted`;
    a ledger record written before they existed parses them as `None`.
    """

    payload = json.loads(json.dumps(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD))
    payload["candidates"][0]["observations"][0].update(
        {"corrected": True, "expression_of_concern": True, "withdrawn": False}
    )

    observation = parse_federated_coverage_report_result(payload).candidates[0].observations[0]

    assert observation.corrected is True
    assert observation.expression_of_concern is True
    assert observation.withdrawn is False
    # Unchanged pre-existing flag, parsed from the same record.
    assert observation.retracted is False

    older = (
        parse_federated_coverage_report_result(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD)
        .candidates[0]
        .observations[0]
    )
    assert older.corrected is None
    assert older.expression_of_concern is None
    assert older.withdrawn is None


def test_parse_federated_coverage_report_result_handles_no_recorded_candidates() -> None:
    """A run persisted before Core's candidate-snapshot follow-up has an honest empty list."""

    payload = dict(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD)
    payload["candidates"] = []

    result = parse_federated_coverage_report_result(payload)

    assert result.candidates == ()


def test_parse_federated_coverage_report_result_raises_on_a_missing_field() -> None:
    payload = {
        k: v for k, v in _VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD.items() if k != "candidates"
    }

    with pytest.raises(FederatedCoverageReportParseError, match="missing a required field"):
        parse_federated_coverage_report_result(payload)


def test_parse_federated_coverage_report_result_raises_on_a_malformed_coverage_record() -> None:
    payload = dict(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD)
    payload["coverage"] = {"search_run_id": "only-one-field"}

    with pytest.raises(FederatedCoverageReportParseError, match="malformed coverage record"):
        parse_federated_coverage_report_result(payload)


def test_parse_federated_coverage_report_result_raises_on_a_malformed_candidate() -> None:
    payload = dict(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD)
    payload["candidates"] = [{"canonical_id": "only-one-field"}]

    with pytest.raises(FederatedCoverageReportParseError, match="malformed candidate"):
        parse_federated_coverage_report_result(payload)


def test_federated_coverage_report_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger_root = tmp_path / "ledger"

    result = federated_coverage_report(
        "33333333-3333-3333-3333-333333333333", ledger_root=ledger_root
    )

    assert result.search_run_id == "33333333-3333-3333-3333-333333333333"
    assert len(result.candidates) == 1
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:3] == [
        "ke",
        "federated-coverage-report",
        "33333333-3333-3333-3333-333333333333",
    ]
    assert "--ledger-root" in command and command[command.index("--ledger-root") + 1] == str(
        ledger_root
    )
    assert "--output" in command


def test_federated_coverage_report_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="exited 1"):
        federated_coverage_report("run-1", ledger_root=tmp_path / "ledger")


def test_federated_coverage_report_raises_when_the_output_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="did not write a readable JSON output file"):
        federated_coverage_report("run-1", ledger_root=tmp_path / "ledger")


def test_federated_coverage_report_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        federated_coverage_report("run-1", ledger_root=tmp_path / "ledger")


def test_federated_coverage_report_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_FEDERATED_COVERAGE_REPORT_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    federated_coverage_report("run-1", ledger_root=tmp_path / "ledger")

    assert captured_kwargs.get("shell", False) is False


_VALID_CITATION_SNOWBALL_PAYLOAD = {
    "snowball_run_id": "22222222-2222-2222-2222-222222222222",
    "provider": "semantic_scholar",
    "plan": {
        "seed_identifiers": ["doi:10.1000/seed"],
        "directions": ["references", "citations"],
        "max_depth": 1,
        "limit_per_traversal": 25,
        "max_candidates": 100,
    },
    "completeness": "complete",
    "truncated": False,
    "candidates": [
        {
            "canonical_id": "doi:10.1000/found",
            "title": "A downstream trial",
            "doi": "10.1000/found",
            "publication_year": 2025,
            "observations": [{"provider": "semantic_scholar"}],
        }
    ],
    "edges": [
        {
            "provider": "semantic_scholar",
            "seed_identifier": "doi:10.1000/seed",
            "related_provider_id": "doi:10.1000/found",
            "direction": "citations",
            "retrieved_at": "2026-08-19T00:00:00Z",
        }
    ],
}


def test_parse_citation_snowball_result_parses_a_valid_payload() -> None:
    result = parse_citation_snowball_result(_VALID_CITATION_SNOWBALL_PAYLOAD)

    assert result.snowball_run_id == "22222222-2222-2222-2222-222222222222"
    assert result.provider == "semantic_scholar"
    assert result.seed_identifiers == ("doi:10.1000/seed",)
    assert result.directions == ("references", "citations")
    assert result.max_depth == 1
    assert result.completeness == "complete"
    assert result.truncated is False
    assert result.candidates[0].title == "A downstream trial"
    assert result.candidates[0].providers == ("semantic_scholar",)
    assert result.edges[0].related_provider_id == "doi:10.1000/found"
    assert result.edges[0].direction == "citations"


def test_parse_citation_snowball_result_preserves_per_provider_retraction_flags() -> None:
    payload = {
        **_VALID_CITATION_SNOWBALL_PAYLOAD,
        "candidates": [
            {
                "canonical_id": "doi:10.1000/found",
                "title": "A downstream trial",
                "doi": "10.1000/found",
                "publication_year": 2025,
                "observations": [
                    {"provider": "semantic_scholar", "retracted": True, "preprint": False},
                ],
            }
        ],
    }

    result = parse_citation_snowball_result(payload)

    flags = result.candidates[0].observation_flags
    assert flags == (
        FederatedProviderObservationFlags(
            provider="semantic_scholar", retracted=True, preprint=False, preprint_version=None
        ),
    )


def test_parse_citation_snowball_result_defaults_observation_flags_to_none_when_absent() -> None:
    result = parse_citation_snowball_result(_VALID_CITATION_SNOWBALL_PAYLOAD)

    flags = result.candidates[0].observation_flags
    assert flags == (
        FederatedProviderObservationFlags(
            provider="semantic_scholar", retracted=None, preprint=None, preprint_version=None
        ),
    )


def test_parse_citation_snowball_result_preserves_independent_publication_status_flags() -> None:
    payload = {
        **_VALID_CITATION_SNOWBALL_PAYLOAD,
        "candidates": [
            {
                "canonical_id": "doi:10.1000/found",
                "title": "A downstream trial",
                "doi": "10.1000/found",
                "publication_year": 2025,
                "observations": [
                    {
                        "provider": "crossref",
                        "corrected": True,
                        "expression_of_concern": True,
                        "withdrawn": True,
                    },
                ],
            }
        ],
    }

    result = parse_citation_snowball_result(payload)

    assert result.candidates[0].observation_flags == (
        FederatedProviderObservationFlags(
            provider="crossref",
            retracted=None,
            preprint=None,
            preprint_version=None,
            corrected=True,
            expression_of_concern=True,
            withdrawn=True,
        ),
    )


def test_parse_citation_snowball_result_raises_on_a_missing_field() -> None:
    payload = {k: v for k, v in _VALID_CITATION_SNOWBALL_PAYLOAD.items() if k != "completeness"}

    with pytest.raises(CitationSnowballParseError, match="missing a required field"):
        parse_citation_snowball_result(payload)


def test_citation_snowball_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_CITATION_SNOWBALL_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger_root = tmp_path / "ledger"

    result = citation_snowball(
        ("doi:10.1000/seed",),
        ledger_root=ledger_root,
        provider="openalex",
        directions=("citations",),
        max_depth=2,
        limit_per_traversal=10,
        max_candidates=50,
        openalex_api_key="key-1",
        semantic_scholar_api_key="key-2",
    )

    assert result.snowball_run_id == "22222222-2222-2222-2222-222222222222"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:6] == [
        "ke",
        "citation-snowball",
        "--seeds",
        "doi:10.1000/seed",
        "--ledger-root",
        str(ledger_root),
    ]
    assert "--provider" in command and command[command.index("--provider") + 1] == "openalex"
    assert "--directions" in command and command[command.index("--directions") + 1] == "citations"
    assert "--max-depth" in command and command[command.index("--max-depth") + 1] == "2"
    assert (
        "--limit-per-traversal" in command
        and command[command.index("--limit-per-traversal") + 1] == "10"
    )
    assert "--max-candidates" in command and command[command.index("--max-candidates") + 1] == "50"
    assert "--openalex-api-key" in command
    assert "--semantic-scholar-api-key" in command
    assert "--output" in command


def test_citation_snowball_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="exited 1"):
        citation_snowball(("doi:10.1000/seed",), ledger_root=tmp_path / "ledger")


def test_citation_snowball_raises_when_the_output_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="did not write a readable JSON output file"):
        citation_snowball(("doi:10.1000/seed",), ledger_root=tmp_path / "ledger")


def test_citation_snowball_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        citation_snowball(("doi:10.1000/seed",), ledger_root=tmp_path / "ledger")


def test_citation_snowball_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_CITATION_SNOWBALL_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    citation_snowball(("doi:10.1000/seed",), ledger_root=tmp_path / "ledger")

    assert "shell" not in captured_kwargs or captured_kwargs["shell"] is False

    assert captured_kwargs.get("shell", False) is False


_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD = {
    "schema_version": 1,
    "search_run_id": "33333333-3333-3333-3333-333333333333",
    "research_question_id": "creatine-strength-thread",
    "query_text": "creatine supplementation maximal strength",
    "requested_candidate_count": 2,
    "resolved_candidate_count": 2,
    "already_indexed_count": 0,
    "full_text_selected_count": 1,
    "metadata_only_count": 1,
    "skipped_budget_count": 0,
    "missing_candidate_count": 0,
    "provider_failures": [],
    "items": [
        {
            "candidate_id": "doi:10.1000/creatine-1",
            "title": "Creatine and maximal strength",
            "disposition": "eligible_full_text",
            "identity": {
                "canonical_id": "doi:10.1000/creatine-1",
                "doi": "10.1000/creatine-1",
                "pmid": "12345",
                "pmcid": None,
                "arxiv_id": None,
                "openalex_id": None,
                "semantic_scholar_id": None,
            },
            "selected_observation_provider": "pubmed",
            "acquisition_route": "pmc_oa",
            "full_text_url": "https://example.org/creatine-1.pdf",
            "xml_url": None,
            "license": "CC BY",
            "open_access": True,
            "existing_paper_id": None,
            "reason": None,
        },
        {
            "candidate_id": "doi:10.1000/creatine-2",
            "title": "A second creatine trial",
            "disposition": "metadata_only",
            "identity": {
                "canonical_id": "doi:10.1000/creatine-2",
                "doi": "10.1000/creatine-2",
                "pmid": None,
                "pmcid": None,
                "arxiv_id": None,
                "openalex_id": None,
                "semantic_scholar_id": None,
            },
            "selected_observation_provider": "crossref",
            "acquisition_route": None,
            "full_text_url": None,
            "xml_url": None,
            "license": None,
            "open_access": None,
            "existing_paper_id": None,
            "reason": "no_eligible_open_full_text_location",
        },
    ],
}


def test_parse_general_question_acquisition_plan_result_parses_a_valid_payload() -> None:
    result = parse_general_question_acquisition_plan_result(
        _VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD
    )

    assert result.search_run_id == "33333333-3333-3333-3333-333333333333"
    assert result.research_question_id == "creatine-strength-thread"
    assert result.requested_candidate_count == 2
    assert result.full_text_selected_count == 1
    assert result.metadata_only_count == 1
    assert result.provider_failures == ()
    assert len(result.items) == 2

    first = result.items[0]
    assert first.candidate_id == "doi:10.1000/creatine-1"
    assert first.disposition == "eligible_full_text"
    assert first.identity is not None
    assert first.identity.doi == "10.1000/creatine-1"
    assert first.identity.pmid == "12345"
    assert first.acquisition_route == "pmc_oa"

    second = result.items[1]
    assert second.disposition == "metadata_only"
    assert second.reason == "no_eligible_open_full_text_location"


def test_parse_general_question_acquisition_plan_result_handles_a_null_identity() -> None:
    payload = {
        **_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD,
        "items": [
            {
                "candidate_id": "doi:10.1000/missing",
                "title": None,
                "disposition": "not_found_in_run",
                "identity": None,
                "selected_observation_provider": None,
                "full_text_url": None,
                "xml_url": None,
                "license": None,
                "open_access": None,
                "existing_paper_id": None,
                "reason": "candidate_not_present_in_persisted_search_snapshot",
            }
        ],
    }

    result = parse_general_question_acquisition_plan_result(payload)

    assert result.items[0].identity is None
    assert result.items[0].disposition == "not_found_in_run"


def test_parse_general_question_acquisition_plan_result_raises_on_a_missing_field() -> None:
    payload = dict(_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD)
    del payload["search_run_id"]

    with pytest.raises(GeneralQuestionAcquisitionParseError):
        parse_general_question_acquisition_plan_result(payload)


def test_parse_general_question_acquisition_plan_result_raises_on_a_malformed_item() -> None:
    payload = {
        **_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD,
        "items": [{"title": "missing candidate_id"}],
    }

    with pytest.raises(GeneralQuestionAcquisitionParseError):
        parse_general_question_acquisition_plan_result(payload)


def test_general_question_acquisition_plan_runs_the_expected_command_and_parses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        request_index = command.index("general-question-acquisition-plan") + 1
        request_payload = json.loads(Path(command[request_index]).read_text(encoding="utf-8"))
        captured["request_payload"] = request_payload
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger_root = tmp_path / "ledger"

    result = general_question_acquisition_plan(
        search_run_id="33333333-3333-3333-3333-333333333333",
        research_question_id="creatine-strength-thread",
        candidate_ids=("doi:10.1000/creatine-1", "doi:10.1000/creatine-2"),
        ledger_root=ledger_root,
        max_candidates=5,
        max_full_text_acquisitions=2,
    )

    assert result.search_run_id == "33333333-3333-3333-3333-333333333333"
    assert len(result.items) == 2

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1] == "general-question-acquisition-plan"
    assert "--ledger-root" in command and command[command.index("--ledger-root") + 1] == str(
        ledger_root
    )
    assert "--no-database" not in command

    request_payload = captured["request_payload"]
    assert isinstance(request_payload, dict)
    assert request_payload["schema_version"] == 1
    assert request_payload["search_run_id"] == "33333333-3333-3333-3333-333333333333"
    assert request_payload["candidate_ids"] == [
        "doi:10.1000/creatine-1",
        "doi:10.1000/creatine-2",
    ]
    assert request_payload["max_candidates"] == 5
    assert request_payload["max_full_text_acquisitions"] == 2


def test_general_question_acquisition_plan_forwards_no_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    general_question_acquisition_plan(
        search_run_id="run-1",
        research_question_id="thread-1",
        candidate_ids=("doi:10.1000/creatine-1",),
        ledger_root=tmp_path / "ledger",
        no_database=True,
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--no-database" in command


def test_general_question_acquisition_plan_raises_on_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(1, "", "boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="exited 1"):
        general_question_acquisition_plan(
            search_run_id="run-1",
            research_question_id="thread-1",
            candidate_ids=("doi:10.1000/creatine-1",),
            ledger_root=tmp_path / "ledger",
        )


def test_general_question_acquisition_plan_raises_when_the_output_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="did not write a readable JSON output file"):
        general_question_acquisition_plan(
            search_run_id="run-1",
            research_question_id="thread-1",
            candidate_ids=("doi:10.1000/creatine-1",),
            ledger_root=tmp_path / "ledger",
        )


def test_general_question_acquisition_plan_raises_a_clear_error_when_ke_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        raise FileNotFoundError("ke")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(KeCommandError, match="is knowledge-engine-core installed"):
        general_question_acquisition_plan(
            search_run_id="run-1",
            research_question_id="thread-1",
            candidate_ids=("doi:10.1000/creatine-1",),
            ledger_root=tmp_path / "ledger",
        )


def test_general_question_acquisition_plan_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_kwargs.update(kwargs)
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_text(
            json.dumps(_VALID_GENERAL_QUESTION_ACQUISITION_PLAN_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    general_question_acquisition_plan(
        search_run_id="run-1",
        research_question_id="thread-1",
        candidate_ids=("doi:10.1000/creatine-1",),
        ledger_root=tmp_path / "ledger",
    )

    assert captured_kwargs.get("shell", False) is False

_VALID_GENERAL_QUESTION_PMC_PERSISTENCE_PAYLOAD = {
    "schema_version": 1,
    "search_run_id": "33333333-3333-3333-3333-333333333333",
    "research_question_id": "creatine-strength-thread",
    "acquisition_route": "pmc_oa",
    "import_run_id": "44444444-4444-4444-4444-444444444444",
    "parsed_count": 1,
    "persisted_count": 1,
    "reused_count": 0,
    "items": [{
        "candidate_id": "doi:10.1000/creatine-1",
        "pmid": "12345",
        "pmcid": "PMC12345",
        "filename": "PMC12345.pdf",
        "sha256": "a" * 64,
        "paper_id": 42,
        "import_item_id": "55555555-5555-5555-5555-555555555555",
        "persistence_status": "persisted",
    }],
}


def test_parse_general_question_pmc_persistence_result_preserves_lineage() -> None:
    result = parse_general_question_pmc_persistence_result(
        _VALID_GENERAL_QUESTION_PMC_PERSISTENCE_PAYLOAD
    )

    assert result.acquisition_route == "pmc_oa"
    assert result.import_run_id == "44444444-4444-4444-4444-444444444444"
    assert result.persisted_count == 1
    assert result.items[0].paper_id == 42
    assert result.items[0].import_item_id == "55555555-5555-5555-5555-555555555555"
    assert result.items[0].persistence_status == "persisted"


def test_parse_general_question_pmc_persistence_result_rejects_missing_lineage() -> None:
    payload = dict(_VALID_GENERAL_QUESTION_PMC_PERSISTENCE_PAYLOAD)
    del payload["import_run_id"]

    with pytest.raises(GeneralQuestionPmcPersistenceParseError, match="required field"):
        parse_general_question_pmc_persistence_result(payload)


def test_general_question_acquire_pmc_runs_expected_command_and_parses_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        request_index = command.index("general-question-acquire-pmc") + 1
        captured["request"] = json.loads(Path(command[request_index]).read_text(encoding="utf-8"))
        receipt_index = command.index("--receipt") + 1
        Path(command[receipt_index]).write_text(
            json.dumps(_VALID_GENERAL_QUESTION_PMC_PERSISTENCE_PAYLOAD), encoding="utf-8"
        )
        return _FakeCompletedProcess(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ledger_root = tmp_path / "ledger"
    papers_dir = tmp_path / "papers"
    core_root = tmp_path / "core"

    result = general_question_acquire_pmc(
        search_run_id="33333333-3333-3333-3333-333333333333",
        research_question_id="creatine-strength-thread",
        candidate_ids=("doi:10.1000/creatine-1",),
        ledger_root=ledger_root,
        papers_dir=papers_dir,
        max_candidates=3,
        max_full_text_acquisitions=1,
        working_directory=core_root,
    )

    assert result.items[0].paper_id == 42
    command = captured["command"]
    assert isinstance(command, list)
    assert command[1] == "general-question-acquire-pmc"
    assert command[command.index("--ledger-root") + 1] == str(ledger_root)
    assert command[command.index("--papers-dir") + 1] == str(papers_dir)
    assert "--receipt" in command
    request = captured["request"]
    assert isinstance(request, dict)
    assert request["candidate_ids"] == ["doi:10.1000/creatine-1"]
    assert request["max_candidates"] == 3
    assert request["max_full_text_acquisitions"] == 1
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == core_root
    assert kwargs.get("shell", False) is False


def test_general_question_acquire_pmc_raises_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: _FakeCompletedProcess(1, "", "sanitized")
    )

    with pytest.raises(KeCommandError, match="exited 1: sanitized"):
        general_question_acquire_pmc(
            search_run_id="run-1",
            research_question_id="thread-1",
            candidate_ids=("doi:10.1000/creatine-1",),
            ledger_root=tmp_path / "ledger",
            papers_dir=tmp_path / "papers",
        )


def test_general_question_acquire_pmc_raises_when_receipt_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: _FakeCompletedProcess(0, ""))

    with pytest.raises(KeCommandError, match="readable JSON receipt"):
        general_question_acquire_pmc(
            search_run_id="run-1",
            research_question_id="thread-1",
            candidate_ids=("doi:10.1000/creatine-1",),
            ledger_root=tmp_path / "ledger",
            papers_dir=tmp_path / "papers",
        )
