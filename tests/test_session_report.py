from __future__ import annotations

from knowledge_engine_ai.models import EvidenceRecord as EvidenceRecordModel
from knowledge_engine_ai.models import (
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.session_report import build_session_report
from knowledge_engine_ai.orchestrator.verification import verify_synthesis


def _record(**overrides: object) -> EvidenceRecordModel:
    base: dict[str, object] = {
        "evidence_record_id": "ev-1",
        "extraction_method": None,
        "extraction_status": None,
        "review_status": None,
        "review_checklist": None,
        "review_notes": None,
        "evidence_direction": "supports",
        "research_question": None,
        "claim_text": "Semaglutide reduced body weight by 14.9% versus placebo.",
        "population": None,
        "intervention": None,
        "comparator": None,
        "outcome": None,
        "result_summary": "Mean difference -12.4 kg (95% CI -13.4 to -11.5).",
        "limitations": [],
        "uncertainty_notes": None,
        "confidence_note": None,
        "source_span": None,
    }
    base.update(overrides)
    return EvidenceRecordModel(**base)  # type: ignore[arg-type]


def _report(records: list[EvidenceRecordModel], **paper_overrides: object) -> EvidenceReport:
    paper_base: dict[str, object] = {
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
        "evidence_records": records,
    }
    paper_base.update(paper_overrides)
    return EvidenceReport(
        schema_version=1,
        question="does semaglutide reduce body weight",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=1,
            draft=0,
            reviewed=1,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="ready.",
        ),
        papers=[RetrievedPaper(**paper_base)],  # type: ignore[arg-type]
        disclaimer="This report is retrieval plus recorded evidence only.",
    )


def test_a_real_citation_resolves_to_a_sourced_claim() -> None:
    report = _report([_record()], title="Gao et al.", citation="Gao et al., 2026")
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]."
    verification = verify_synthesis(narrative, report)

    session_report = build_session_report(narrative, report, verification)

    assert len(session_report.sourced_claims) == 1
    claim = session_report.sourced_claims[0]
    assert claim.evidence_record_id == "ev-1"
    assert claim.claim_text == "Semaglutide reduced body weight by 14.9% versus placebo."
    assert claim.paper_title == "Gao et al."
    assert claim.paper_citation == "Gao et al., 2026"
    assert session_report.unresolved_citations == ()
    assert session_report.is_fully_sourced is True


def test_a_hallucinated_citation_lands_in_unresolved_not_sourced_claims() -> None:
    report = _report([_record()])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]. Also see [ev-does-not-exist]."
    verification = verify_synthesis(narrative, report)

    session_report = build_session_report(narrative, report, verification)

    assert [claim.evidence_record_id for claim in session_report.sourced_claims] == ["ev-1"]
    assert session_report.unresolved_citations == ("ev-does-not-exist",)
    assert session_report.is_fully_sourced is False


def test_a_citation_repeated_twice_resolves_to_one_sourced_claim() -> None:
    report = _report([_record()])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]. Confirmed again [ev-1]."
    verification = verify_synthesis(narrative, report)

    session_report = build_session_report(narrative, report, verification)

    assert len(session_report.sourced_claims) == 1


def test_is_fully_sourced_true_only_when_unresolved_citations_empty() -> None:
    report = _report([_record()])
    clean_narrative = "Semaglutide reduced weight by 14.9% [ev-1]."
    clean_verification = verify_synthesis(clean_narrative, report)
    clean_session_report = build_session_report(clean_narrative, report, clean_verification)

    assert clean_session_report.is_fully_sourced is True

    dirty_narrative = "See [ev-missing]."
    dirty_verification = verify_synthesis(dirty_narrative, report)
    dirty_session_report = build_session_report(dirty_narrative, report, dirty_verification)

    assert dirty_session_report.is_fully_sourced is False


def test_narrative_and_verification_are_carried_through_unmodified() -> None:
    report = _report([_record()])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]."
    verification = verify_synthesis(narrative, report)

    session_report = build_session_report(narrative, report, verification)

    assert session_report.narrative == narrative
    assert session_report.verification is verification
