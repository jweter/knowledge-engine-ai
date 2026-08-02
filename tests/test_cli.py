from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import knowledge_engine_ai.cli as cli
from knowledge_engine_ai.cli import app
from knowledge_engine_ai.ke_client import KeCommandError
from knowledge_engine_ai.models import (
    ClaimConfidence,
    EvidenceConsensus,
    EvidenceCoverage,
    EvidenceIntelligence,
    EvidenceQuality,
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)


def _unwrapped(output: str) -> str:
    """Collapse Rich's line-wrapping so substring assertions survive it."""

    return " ".join(output.split())


def _report(*, papers: list[RetrievedPaper] | None = None) -> EvidenceReport:
    return EvidenceReport(
        schema_version=1,
        question="does semaglutide reduce lean mass",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=1,
            draft=1,
            reviewed=0,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="draft only; secondary review needed.",
        ),
        papers=papers if papers is not None else [],
        disclaimer="This report is retrieval plus recorded evidence only.",
    )


def test_ask_prints_a_compact_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = RetrievedPaper(
        rank=1,
        paper_id=42,
        title="A Trial of Semaglutide",
        authors="A. Author",
        year="2026",
        journal="A Journal",
        doi="10.1000/example",
        source_url="https://example.org",
        license_type="CC BY",
        metadata_source="corpus sources.csv",
        retrieval_score=-5.1,
        retrieval_snippet="semaglutide reduced lean mass",
        why_matched="Matched indexed title, abstract, or body text using: semaglutide",
        citation="A Trial of Semaglutide. (2026).",
        evidence_records=[
            EvidenceRecord(
                evidence_record_id="ev-1",
                extraction_method="manual_human_review",
                extraction_status="draft_manual_prototype",
                review_status="draft",
                review_checklist=None,
                review_notes=None,
                evidence_direction="supports",
                research_question=None,
                claim_text="Semaglutide reduced lean mass.",
                population=None,
                intervention=None,
                comparator=None,
                outcome=None,
                result_summary=None,
                limitations=[],
                uncertainty_notes=None,
                confidence_note=None,
                source_span=None,
            )
        ],
    )
    monkeypatch.setattr(
        cli, "enriched_evidence_report", lambda *args, **kwargs: _report(papers=[paper])
    )
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0
    unwrapped = _unwrapped(result.output)
    assert "A Trial of Semaglutide" in unwrapped
    assert "10.1000/example" in unwrapped
    assert "Semaglutide reduced lean mass." in unwrapped
    assert "retrieval plus recorded evidence only" in unwrapped


def test_ask_reports_no_papers_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "enriched_evidence_report", lambda *args, **kwargs: _report(papers=[]))
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0
    assert "No relevant papers found" in _unwrapped(result.output)


def test_ask_exits_nonzero_and_prints_the_error_on_a_ke_command_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_evidence_report(*args: object, **kwargs: object) -> EvidenceReport:
        raise KeCommandError("ke evidence-report exited 1: No relevant papers found.")

    monkeypatch.setattr(cli, "enriched_evidence_report", fake_evidence_report)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 1
    assert "No relevant papers found" in _unwrapped(result.output)


def test_ask_fails_for_a_missing_sources_file(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(tmp_path / "does-not-exist.csv"),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code != 0


def _paper_with_intelligence() -> RetrievedPaper:
    intelligence = EvidenceIntelligence(
        schema_version=1,
        evidence_record_id="ev-1",
        claim_id=1,
        evidence_quality=EvidenceQuality(
            score=94, study_design_tier="randomized_controlled_trial", manually_reviewed=True
        ),
        evidence_consensus=EvidenceConsensus(
            relationship_edge_count=2,
            supports_count=2,
            contradicts_count=0,
            agreement_total=2,
            score=100,
            reliability="moderate",
        ),
        claim_confidence=ClaimConfidence(score=89, reliability="moderate"),
        evidence_coverage=EvidenceCoverage(
            records_in_relationship=7, total_records=155, percentage=5
        ),
        synthesis=["Evidence Quality: 94/100.", "Evidence Consensus: 100/100."],
        scope_note="Every number above is computed deterministically.",
    )
    return RetrievedPaper(
        rank=1,
        paper_id=42,
        title="A Trial of Semaglutide",
        authors="A. Author",
        year="2026",
        journal="A Journal",
        doi="10.1000/example",
        source_url="https://example.org",
        license_type="CC BY",
        metadata_source="corpus sources.csv",
        retrieval_score=-5.1,
        retrieval_snippet="semaglutide reduced lean mass",
        why_matched="Matched indexed title, abstract, or body text using: semaglutide",
        citation="A Trial of Semaglutide. (2026).",
        evidence_records=[
            EvidenceRecord(
                evidence_record_id="ev-1",
                extraction_method="manual_human_review",
                extraction_status="draft_manual_prototype",
                review_status="draft",
                review_checklist=None,
                review_notes=None,
                evidence_direction="supports",
                research_question=None,
                claim_text="Semaglutide reduced lean mass.",
                population=None,
                intervention=None,
                comparator=None,
                outcome=None,
                result_summary=None,
                limitations=[],
                uncertainty_notes=None,
                confidence_note=None,
                source_span=None,
                evidence_intelligence=intelligence,
            )
        ],
    )


def test_ask_shows_evidence_intelligence_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0, result.output
    unwrapped = _unwrapped(result.output)
    assert "Evidence Quality: 94/100" in unwrapped
    assert "Evidence Consensus: 100 (moderate)" in unwrapped
    assert "Claim Confidence: 89 (moderate)" in unwrapped


def test_ask_format_json_prints_valid_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    record = payload["papers"][0]["evidence_records"][0]
    assert record["evidence_intelligence"]["evidence_quality"]["score"] == 94
    assert record["evidence_intelligence"]["claim_confidence"]["score"] == 89


def test_ask_rejects_an_invalid_format(tmp_path: Path) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--format",
            "xml",
        ],
    )

    assert result.exit_code != 0
