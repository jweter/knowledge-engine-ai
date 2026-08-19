from __future__ import annotations

import dataclasses
import json

import pytest
from typer.testing import CliRunner

import knowledge_engine_ai.cli as cli
from knowledge_engine_ai.cli import app
from knowledge_engine_ai.ke_client import (
    CitationSnowballCandidate,
    CitationSnowballEdge,
    CitationSnowballResult,
    FederatedProviderObservationFlags,
    KeCommandError,
)


def _unwrapped(output: str) -> str:
    """Collapse Rich's line-wrapping so substring assertions survive it."""

    return " ".join(output.split())


def _result(
    *,
    completeness: str = "complete",
    truncated: bool = False,
) -> CitationSnowballResult:
    return CitationSnowballResult(
        snowball_run_id="snowball-abc-123",
        provider="semantic_scholar",
        seed_identifiers=("10.1000/example",),
        directions=("references", "citations"),
        max_depth=1,
        limit_per_traversal=25,
        max_candidates=100,
        completeness=completeness,
        truncated=truncated,
        candidates=(
            CitationSnowballCandidate(
                canonical_id="semantic_scholar:abc123",
                title="A Related Trial of Semaglutide for Body Weight Reduction",
                doi="10.1000/related",
                publication_year=2025,
                providers=("semantic_scholar",),
            ),
        ),
        edges=(
            CitationSnowballEdge(
                provider="semantic_scholar",
                seed_identifier="10.1000/example",
                related_provider_id="abc123",
                direction="citations",
                retrieved_at="2026-08-15T11:22:00+00:00",
            ),
        ),
    )


def test_citation_snowball_prints_coverage_and_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_citation_snowball(
        seed_identifiers: tuple[str, ...], **kwargs: object
    ) -> CitationSnowballResult:
        calls.append({"seed_identifiers": seed_identifiers, **kwargs})
        return _result()

    monkeypatch.setattr(cli, "citation_snowball", fake_citation_snowball)

    result = CliRunner().invoke(
        app,
        [
            "citation-snowball",
            "--seeds",
            "10.1000/example",
            "--ledger-root",
            "/tmp/ledger",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls and calls[0]["seed_identifiers"] == ("10.1000/example",)

    body = _unwrapped(result.output)
    assert "snowball-abc-123" in body
    assert "Provider: semantic_scholar" in body
    assert "Seeds: 10.1000/example" in body
    assert "Coverage: complete" in body
    assert "A Related Trial of Semaglutide for Body Weight Reduction" in body
    assert "observed by: semantic_scholar" in body
    assert "not Evidence Records and were not acquired" in body


def test_citation_snowball_shows_retracted_and_preprint_flags_per_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = CitationSnowballCandidate(
        canonical_id="semantic_scholar:abc123",
        title="A Related Trial",
        doi="10.1000/related",
        publication_year=2025,
        providers=("arxiv", "semantic_scholar"),
        observation_flags=(
            FederatedProviderObservationFlags(
                provider="semantic_scholar", retracted=True, preprint=False, preprint_version=None
            ),
            FederatedProviderObservationFlags(
                provider="arxiv", retracted=False, preprint=True, preprint_version=2
            ),
        ),
    )
    result_with_flags = dataclasses.replace(_result(), candidates=(candidate,))
    monkeypatch.setattr(cli, "citation_snowball", lambda seeds, **kwargs: result_with_flags)

    result = CliRunner().invoke(
        app, ["citation-snowball", "--seeds", "10.1000/example", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code == 0, result.output
    body = _unwrapped(result.output)
    assert "semantic_scholar: retracted" in body
    assert "arxiv: preprint v2" in body


def test_citation_snowball_notes_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "citation_snowball", lambda seeds, **kwargs: _result(truncated=True))

    result = CliRunner().invoke(
        app, ["citation-snowball", "--seeds", "10.1000/example", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code == 0, result.output
    assert "truncated at --max-candidates" in _unwrapped(result.output)


def test_citation_snowball_forwards_provider_directions_and_api_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_citation_snowball(
        seed_identifiers: tuple[str, ...], **kwargs: object
    ) -> CitationSnowballResult:
        calls.append(kwargs)
        return _result()

    monkeypatch.setattr(cli, "citation_snowball", fake_citation_snowball)

    result = CliRunner().invoke(
        app,
        [
            "citation-snowball",
            "--seeds",
            "10.1000/example,arxiv:2301.12345",
            "--ledger-root",
            "/tmp/ledger",
            "--provider",
            "openalex",
            "--directions",
            "references",
            "--max-depth",
            "2",
            "--limit-per-traversal",
            "10",
            "--max-candidates",
            "50",
            "--openalex-api-key",
            "test-key",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["provider"] == "openalex"
    assert calls[0]["directions"] == ("references",)
    assert calls[0]["max_depth"] == 2
    assert calls[0]["limit_per_traversal"] == 10
    assert calls[0]["max_candidates"] == 50
    assert calls[0]["openalex_api_key"] == "test-key"


def test_citation_snowball_writes_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "citation_snowball", lambda seeds, **kwargs: _result())

    result = CliRunner().invoke(
        app,
        [
            "citation-snowball",
            "--seeds",
            "10.1000/example",
            "--ledger-root",
            "/tmp/ledger",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["snowball_run_id"] == "snowball-abc-123"
    assert payload["completeness"] == "complete"
    assert payload["candidates"][0]["canonical_id"] == "semantic_scholar:abc123"


def test_citation_snowball_reports_ke_command_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(seed_identifiers: tuple[str, ...], **kwargs: object) -> CitationSnowballResult:
        raise KeCommandError("`ke citation-snowball` exited 1: boom")

    monkeypatch.setattr(cli, "citation_snowball", fail)

    result = CliRunner().invoke(
        app, ["citation-snowball", "--seeds", "10.1000/example", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code == 1
    assert "boom" in result.output


def test_citation_snowball_rejects_an_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "citation_snowball", lambda seeds, **kwargs: _result())

    result = CliRunner().invoke(
        app,
        [
            "citation-snowball",
            "--seeds",
            "10.1000/example",
            "--ledger-root",
            "/tmp/ledger",
            "--format",
            "xml",
        ],
    )

    assert result.exit_code != 0


def test_citation_snowball_rejects_empty_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "citation_snowball", lambda seeds, **kwargs: _result())

    result = CliRunner().invoke(
        app, ["citation-snowball", "--seeds", " , ", "--ledger-root", "/tmp/ledger"]
    )

    assert result.exit_code != 0


def test_citation_snowball_rejects_empty_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "citation_snowball", lambda seeds, **kwargs: _result())

    result = CliRunner().invoke(
        app,
        [
            "citation-snowball",
            "--seeds",
            "10.1000/example",
            "--ledger-root",
            "/tmp/ledger",
            "--directions",
            " , ",
        ],
    )

    assert result.exit_code != 0
