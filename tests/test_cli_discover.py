from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import knowledge_engine_ai.cli as cli
from knowledge_engine_ai.cli import app
from knowledge_engine_ai.ke_client import (
    FederatedCandidateDisagreements,
    FederatedCandidateSummary,
    FederatedDiscoveryResult,
    FederatedProviderAssertion,
    FederatedProviderDisagreement,
    FederatedProviderStatus,
    KeCommandError,
)


def _unwrapped(output: str) -> str:
    """Collapse Rich's line-wrapping so substring assertions survive it."""

    return " ".join(output.split())


def _result(
    *,
    completeness: str = "complete",
    provider_disagreements: tuple[FederatedCandidateDisagreements, ...] | None = (),
) -> FederatedDiscoveryResult:
    return FederatedDiscoveryResult(
        search_run_id="run-abc-123",
        query_text="semaglutide weight loss",
        completeness=completeness,
        provider_statuses=(
            FederatedProviderStatus(
                provider="pubmed", outcome="success", attempted=True, result_count=1, reason=None
            ),
            FederatedProviderStatus(
                provider="openalex",
                outcome="rate_limited",
                attempted=True,
                result_count=0,
                reason="provider_rate_limited",
            ),
        ),
        candidates=(
            FederatedCandidateSummary(
                canonical_id="pubmed:12345",
                title="A Trial of Semaglutide for Body Weight Reduction",
                doi="10.1000/example",
                publication_year=2026,
                providers=("pubmed",),
            ),
        ),
        provider_disagreements=provider_disagreements,
    )


def test_discover_prints_coverage_and_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_federated_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        calls.append({"query": query, **kwargs})
        return _result()

    monkeypatch.setattr(cli, "federated_discover", fake_federated_discover)

    result = CliRunner().invoke(
        app,
        [
            "discover",
            "semaglutide weight loss",
            "--ledger-root",
            "/tmp/ledger",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls and calls[0]["query"] == "semaglutide weight loss"

    body = _unwrapped(result.output)
    assert "run-abc-123" in body
    assert "Coverage: complete" in body
    assert "pubmed: success" in body
    assert "openalex: rate_limited (provider_rate_limited)" in body
    assert "A Trial of Semaglutide for Body Weight Reduction" in body
    assert "observed by: pubmed" in body
    assert "not Evidence Records and were not acquired" in body


def test_discover_forwards_providers_and_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_federated_discover(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        calls.append(kwargs)
        return _result()

    monkeypatch.setattr(cli, "federated_discover", fake_federated_discover)

    result = CliRunner().invoke(
        app,
        [
            "discover",
            "semaglutide weight loss",
            "--ledger-root",
            "/tmp/ledger",
            "--providers",
            "pubmed,openalex",
            "--openalex-api-key",
            "test-key",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["providers"] == ("pubmed", "openalex")
    assert calls[0]["openalex_api_key"] == "test-key"
    assert calls[0]["limit"] == 5


def test_discover_writes_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "federated_discover", lambda query, **kwargs: _result())

    result = CliRunner().invoke(
        app,
        ["discover", "semaglutide weight loss", "--ledger-root", "/tmp/ledger", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["search_run_id"] == "run-abc-123"
    assert payload["completeness"] == "complete"
    assert payload["candidates"][0]["canonical_id"] == "pubmed:12345"


def test_discover_shows_disagreement_summary_without_calling_it_a_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disagreements = (
        FederatedCandidateDisagreements(
            canonical_id="pubmed:12345",
            disagreements=(
                FederatedProviderDisagreement(
                    field="publication_year",
                    assertions=(
                        FederatedProviderAssertion(
                            provider="pubmed", provider_id="12345", value=2025
                        ),
                        FederatedProviderAssertion(
                            provider="crossref", provider_id="10.1000/example", value=2026
                        ),
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "federated_discover",
        lambda query, **kwargs: _result(provider_disagreements=disagreements),
    )

    result = CliRunner().invoke(
        app, ["discover", "semaglutide weight loss", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code == 0, result.output
    body = _unwrapped(result.output)
    assert "Provider metadata disagreements: 1 candidate(s)" in body
    assert "not scientific contradiction" in body


def test_discover_notes_when_disagreement_data_predates_this_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli, "federated_discover", lambda query, **kwargs: _result(provider_disagreements=None)
    )

    result = CliRunner().invoke(
        app, ["discover", "semaglutide weight loss", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code == 0, result.output
    assert "predates provider-disagreement reporting" in result.output


def test_discover_reports_ke_command_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(query: str, **kwargs: object) -> FederatedDiscoveryResult:
        raise KeCommandError("`ke federated-discover` exited 1: boom")

    monkeypatch.setattr(cli, "federated_discover", fail)

    result = CliRunner().invoke(
        app, ["discover", "semaglutide weight loss", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code == 1
    assert "boom" in result.output


def test_discover_rejects_an_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "federated_discover", lambda query, **kwargs: _result())

    result = CliRunner().invoke(
        app,
        [
            "discover",
            "semaglutide weight loss",
            "--ledger-root",
            "/tmp/ledger",
            "--format",
            "xml",
        ],
    )

    assert result.exit_code != 0
