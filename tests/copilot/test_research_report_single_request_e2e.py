"""Single-request Research Report end-to-end behavior.

Drives ``generate_research_report`` with a fake model so that the whole
prompt -> model JSON -> validation -> provenance path is exercised for the three
evidence-integrity situations a real request can hit: missing sources,
contradictory sources, and citation validation. Claims without verifiable
citations must be rejected or explicitly marked uncertain, never accepted.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from knowledge_engine_ai.copilot.research_report import (
    ReportCertainty,
    ResearchReportError,
    generate_research_report,
)
from knowledge_engine_ai.models import EvidenceReport, EvidenceSummary
from tests.copilot.test_research_report import (
    _evidence_report,
    _FakeLLM,
    _payload,
    _progress_report,
)

QUESTION = "Does the exposure increase blood pressure?"


def _no_sources_report() -> EvidenceReport:
    return EvidenceReport(
        schema_version=1,
        question=QUESTION,
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=0,
            draft=0,
            reviewed=0,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="no evidence",
        ),
        papers=[],
        disclaimer="Evidence only.",
    )


def _run(report: EvidenceReport, payload: dict[str, Any]) -> tuple[Any, _FakeLLM]:
    llm = _FakeLLM(json.dumps(payload))
    result = generate_research_report(QUESTION, report, _progress_report(), llm)
    return result, llm


# --- missing sources -------------------------------------------------------


def test_no_sources_fails_closed_before_the_model_is_called() -> None:
    llm = _FakeLLM(json.dumps(_payload()))

    with pytest.raises(ResearchReportError, match="at least one grounded EvidenceRecord"):
        generate_research_report(QUESTION, _no_sources_report(), _progress_report(), llm)

    assert llm.prompts == []


def test_partially_missing_evidence_may_be_marked_unavailable_with_disclosure() -> None:
    payload = copy.deepcopy(_payload())
    payload["conclusion_rows"].append(  # type: ignore[attr-defined]
        {
            "question_dimension": "long_term_outcomes",
            "conclusion": "No retrieved evidence addresses long-term outcomes.",
            "certainty": "unavailable",
            "certainty_rationale": "No retrieved record covers this dimension.",
            "supporting_evidence_ids": [],
            "contradicting_or_null_evidence_ids": [],
            "directness": "direct",
            "missing_direct_evidence": "No long-term outcome evidence was retrieved.",
        }
    )
    llm = _FakeLLM(json.dumps(payload))

    report = generate_research_report(QUESTION, _evidence_report(), _progress_report(), llm)

    unavailable = [r for r in report.conclusion_rows if r.certainty is ReportCertainty.UNAVAILABLE]
    assert [r.question_dimension for r in unavailable] == ["long_term_outcomes"]
    assert unavailable[0].missing_direct_evidence


def test_partially_missing_evidence_rejects_fabricated_citation() -> None:
    payload = copy.deepcopy(_payload())
    row = payload["conclusion_rows"][0]  # type: ignore[index]
    row["supporting_evidence_ids"] = ["ev-invented"]

    with pytest.raises(ResearchReportError, match="unknown evidence ID"):
        _run(_evidence_report(), payload)


# --- contradictory sources -------------------------------------------------


def test_contradictory_sources_are_both_carried_into_the_report() -> None:
    report, llm = _run(_evidence_report(), _payload())

    supporting = {i for r in report.conclusion_rows for i in r.supporting_evidence_ids}
    contradicting = {
        i for r in report.conclusion_rows for i in r.contradicting_or_null_evidence_ids
    }
    assert supporting == {"ev-positive"}
    assert contradicting == {"ev-null"}
    assert "ev-positive" in llm.prompts[0]
    assert "ev-null" in llm.prompts[0]


def test_contradictory_source_cannot_be_silently_dropped() -> None:
    payload = copy.deepcopy(_payload())
    for row in payload["conclusion_rows"]:  # type: ignore[attr-defined]
        row["contradicting_or_null_evidence_ids"] = []
        row["certainty_rationale"] = "Direct trial supports the effect [ev-positive]."
        row["conclusion"] = "Blood pressure rises [ev-positive]."
        row["supporting_evidence_ids"] = ["ev-positive"]
        row["directness"] = "direct"
        row["missing_direct_evidence"] = None
    payload["narrative_sections"] = []
    payload["bottom_line"] = "Blood pressure rises [ev-positive]."
    payload["indirect_evidence_summary"] = "None."

    with pytest.raises(ResearchReportError, match="ev-null"):
        _run(_evidence_report(), payload)


def test_same_evidence_cannot_be_both_supporting_and_contradicting() -> None:
    payload = copy.deepcopy(_payload())
    payload["conclusion_rows"][0]["contradicting_or_null_evidence_ids"] = [  # type: ignore[index]
        "ev-positive"
    ]

    with pytest.raises(ResearchReportError, match="both supporting and contradicting"):
        _run(_evidence_report(), payload)


# --- citation validation ---------------------------------------------------


def test_every_accepted_citation_resolves_to_a_retrieved_evidence_record() -> None:
    report, _ = _run(_evidence_report(), _payload())
    known = {"ev-positive", "ev-null"}

    for row in report.conclusion_rows:
        assert set(row.supporting_evidence_ids) <= known
        assert set(row.contradicting_or_null_evidence_ids) <= known
        assert row.supporting_evidence_ids or row.contradicting_or_null_evidence_ids


def test_unknown_citation_in_bottom_line_is_rejected() -> None:
    payload = copy.deepcopy(_payload())
    payload["bottom_line"] = "Blood pressure rises [ev-invented]."

    with pytest.raises(ResearchReportError, match="ev-invented"):
        _run(_evidence_report(), payload)


def test_claim_citing_evidence_outside_its_row_authority_is_rejected() -> None:
    payload = copy.deepcopy(_payload())
    payload["conclusion_rows"][0]["conclusion"] = (  # type: ignore[index]
        "Blood pressure rises [ev-positive] and [ev-null]."
    )

    with pytest.raises(ResearchReportError, match="ev-null"):
        _run(_evidence_report(), payload)


def test_certainty_without_grounded_evidence_ids_is_rejected() -> None:
    payload = copy.deepcopy(_payload())
    row = payload["conclusion_rows"][0]  # type: ignore[index]
    row["supporting_evidence_ids"] = []
    row["conclusion"] = "Blood pressure rises."
    row["certainty_rationale"] = "Widely believed."

    with pytest.raises(ResearchReportError, match="without any grounded evidence IDs"):
        _run(_evidence_report(), payload)
