from __future__ import annotations

from knowledge_engine_ai.models import EvidenceRecord as EvidenceRecordModel
from knowledge_engine_ai.models import (
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
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


def _report(records: list[EvidenceRecordModel]) -> EvidenceReport:
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
        papers=[
            RetrievedPaper(
                rank=1,
                paper_id=1,
                title="T",
                authors="A",
                year="2026",
                journal="J",
                doi="10.1/x",
                source_url="https://example.org",
                license_type="CC BY",
                metadata_source="sources.csv",
                retrieval_score=-1.0,
                retrieval_snippet="s",
                why_matched="m",
                citation="c",
                evidence_records=records,
            )
        ],
        disclaimer="This report is retrieval plus recorded evidence only.",
    )


def test_clean_narrative_is_clean() -> None:
    report = _report([_record()])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]."

    result = verify_synthesis(narrative, report)

    assert result.is_clean is True
    assert result.hallucinated_citations == ()
    assert result.ungrounded_numbers == ()
    assert result.missed_qualifiers == ()


def test_catches_a_hallucinated_citation() -> None:
    report = _report([_record()])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]. Also see [ev-does-not-exist]."

    result = verify_synthesis(narrative, report)

    assert result.is_clean is False
    assert result.hallucinated_citations == ("ev-does-not-exist",)


def test_catches_an_ungrounded_number() -> None:
    report = _report([_record()])
    narrative = "Semaglutide reduced weight by 99.9% [ev-1]."

    result = verify_synthesis(narrative, report)

    assert result.is_clean is False
    assert "99.9" in result.ungrounded_numbers


def test_tolerates_a_number_grounded_in_a_different_cited_record_field() -> None:
    report = _report([_record()])
    # -12.4 appears only in result_summary, not claim_text -- still grounded.
    narrative = "The mean difference was -12.4 kg [ev-1]."

    result = verify_synthesis(narrative, report)

    assert result.ungrounded_numbers == ()


def test_catches_a_missed_qualifier_from_evidence_direction() -> None:
    qualifying = _record(
        evidence_record_id="ev-2",
        evidence_direction="qualifies",
        claim_text="A subgroup showed no significant difference.",
        result_summary="p = 0.34, underpowered.",
    )
    report = _report([_record(), qualifying])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]."

    result = verify_synthesis(narrative, report)

    assert result.is_clean is False
    assert result.missed_qualifiers == ("ev-2",)


def test_catches_a_missed_qualifier_from_limitations() -> None:
    limited = _record(
        evidence_record_id="ev-2",
        limitations=["Small sample size (n=12)."],
    )
    report = _report([_record(), limited])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]."

    result = verify_synthesis(narrative, report)

    assert result.missed_qualifiers == ("ev-2",)


def test_a_cited_qualifying_record_is_not_flagged_as_missed() -> None:
    qualifying = _record(
        evidence_record_id="ev-2",
        evidence_direction="qualifies",
    )
    report = _report([_record(), qualifying])
    narrative = "Semaglutide reduced weight by 14.9% [ev-1]. A subgroup differed [ev-2]."

    result = verify_synthesis(narrative, report)

    assert result.missed_qualifiers == ()
    assert result.is_clean is True


def test_records_without_evidence_record_id_are_ignored() -> None:
    report = _report([_record(evidence_record_id=None)])
    narrative = "Semaglutide reduced weight."

    result = verify_synthesis(narrative, report)

    assert result.is_clean is True


def test_empty_narrative_against_a_qualifying_report_is_flagged() -> None:
    report = _report([_record(evidence_direction="contradicts")])

    result = verify_synthesis("No relevant claims found.", report)

    assert result.missed_qualifiers == ("ev-1",)
