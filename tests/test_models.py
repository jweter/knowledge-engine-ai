from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine_ai.models import (
    EvidenceIntelligenceParseError,
    EvidenceReportParseError,
    parse_evidence_intelligence,
    parse_evidence_report,
)

_VALID_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "question": "does semaglutide reduce lean mass",
    "sources_path": "sources.csv",
    "evidence_path": "evidence_records.jsonl",
    "evidence_summary": {
        "total": 1,
        "draft": 1,
        "reviewed": 0,
        "needs_revision": 0,
        "rejected": 0,
        "unspecified": 0,
        "readiness_note": "draft only; secondary review needed.",
    },
    "papers": [
        {
            "rank": 1,
            "paper_id": 42,
            "title": "A Trial of Semaglutide",
            "authors": "A. Author",
            "year": "2026",
            "journal": "A Journal",
            "doi": "10.1000/example",
            "source_url": "https://example.org",
            "license_type": "CC BY",
            "metadata_source": "corpus sources.csv",
            "retrieval_score": -5.1,
            "retrieval_snippet": "semaglutide reduced lean mass",
            "why_matched": "Matched indexed title, abstract, or body text using: semaglutide",
            "citation": "A Trial of Semaglutide. (2026). DOI: 10.1000/example.",
            "evidence_records": [
                {
                    "evidence_record_id": "ev-1",
                    "extraction_method": "manual_human_review",
                    "extraction_status": "draft_manual_prototype",
                    "review_status": "draft",
                    "review_checklist": {"source_verified": True},
                    "review_notes": None,
                    "evidence_direction": "supports",
                    "research_question": "Does semaglutide reduce lean mass?",
                    "claim_text": "Semaglutide reduced lean mass.",
                    "population": "Adults with obesity.",
                    "intervention": "Semaglutide.",
                    "comparator": "Placebo.",
                    "outcome": "Lean mass change.",
                    "result_summary": "Lean mass decreased by 2%.",
                    "limitations": ["Single trial."],
                    "uncertainty_notes": None,
                    "confidence_note": None,
                    "source_span": {"page_number": 2},
                }
            ],
        }
    ],
    "disclaimer": "This report is retrieval plus recorded evidence only.",
}


def test_parse_evidence_report_returns_a_fully_typed_report() -> None:
    report = parse_evidence_report(_VALID_PAYLOAD)

    assert report.schema_version == 1
    assert report.question == "does semaglutide reduce lean mass"
    assert report.evidence_summary.total == 1
    assert len(report.papers) == 1
    paper = report.papers[0]
    assert paper.title == "A Trial of Semaglutide"
    assert len(paper.evidence_records) == 1
    record = paper.evidence_records[0]
    assert record.evidence_record_id == "ev-1"
    assert record.claim_text == "Semaglutide reduced lean mass."
    assert record.limitations == ["Single trial."]


def test_parse_evidence_report_handles_zero_papers() -> None:
    payload = dict(_VALID_PAYLOAD, papers=[])

    report = parse_evidence_report(payload)

    assert report.papers == []


def test_parse_evidence_report_rejects_an_unsupported_schema_version() -> None:
    payload = dict(_VALID_PAYLOAD, schema_version=2)

    with pytest.raises(EvidenceReportParseError, match="schema_version"):
        parse_evidence_report(payload)


def test_parse_evidence_report_rejects_a_missing_required_field() -> None:
    payload = dict(_VALID_PAYLOAD)
    del payload["question"]

    with pytest.raises(EvidenceReportParseError, match="missing field"):
        parse_evidence_report(payload)


def test_parse_evidence_report_defaults_missing_optional_evidence_record_fields() -> None:
    payload = dict(_VALID_PAYLOAD)
    payload["papers"] = [dict(payload["papers"][0])]
    payload["papers"][0]["evidence_records"] = [{"evidence_record_id": "ev-2"}]

    report = parse_evidence_report(payload)

    record = report.papers[0].evidence_records[0]
    assert record.evidence_record_id == "ev-2"
    assert record.claim_text is None
    assert record.limitations == []


_VALID_INTELLIGENCE_PAYLOAD: dict[str, Any] = {
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


def test_parse_evidence_intelligence_returns_a_fully_typed_result() -> None:
    intelligence = parse_evidence_intelligence(_VALID_INTELLIGENCE_PAYLOAD)

    assert intelligence.schema_version == 1
    assert intelligence.evidence_record_id == "ev-1"
    assert intelligence.claim_id == 1
    assert intelligence.evidence_quality.score == 94
    assert intelligence.evidence_consensus.agreement_total == 2
    assert intelligence.claim_confidence.score == 89
    assert intelligence.evidence_coverage.percentage == 5
    assert intelligence.synthesis == ["Evidence Quality: 94/100."]


def test_parse_evidence_intelligence_handles_not_yet_assessable_scores() -> None:
    payload = dict(_VALID_INTELLIGENCE_PAYLOAD)
    payload["evidence_consensus"] = dict(
        payload["evidence_consensus"], score=None, reliability="insufficient"
    )
    payload["claim_confidence"] = {"score": None, "reliability": "insufficient"}

    intelligence = parse_evidence_intelligence(payload)

    assert intelligence.evidence_consensus.score is None
    assert intelligence.claim_confidence.score is None


def test_parse_evidence_intelligence_rejects_an_unsupported_schema_version() -> None:
    payload = dict(_VALID_INTELLIGENCE_PAYLOAD, schema_version=2)

    with pytest.raises(EvidenceIntelligenceParseError, match="schema_version"):
        parse_evidence_intelligence(payload)


def test_parse_evidence_intelligence_rejects_a_missing_required_field() -> None:
    payload = dict(_VALID_INTELLIGENCE_PAYLOAD)
    del payload["claim_id"]

    with pytest.raises(EvidenceIntelligenceParseError, match="missing field"):
        parse_evidence_intelligence(payload)
