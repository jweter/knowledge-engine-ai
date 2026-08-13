from __future__ import annotations

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
from knowledge_engine_ai.synthesis import build_synthesis_prompt, synthesize_answer


class _FakeLLM:
    def __init__(self, response: str = "Synthesized answer.") -> None:
        self.response = response
        self.prompts: list[str] = []
        self.max_tokens_seen: list[int] = []
        self.timeouts_seen: list[float | None] = []

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        self.prompts.append(prompt)
        self.max_tokens_seen.append(max_tokens)
        self.timeouts_seen.append(timeout_seconds)

        return self.response


def test_synthesize_answer_forwards_the_execution_timeout() -> None:
    llm = _FakeLLM("Answer [ev-1].")

    synthesize_answer(_report(papers=[_paper_with_evidence()]), llm, timeout_seconds=12.5)

    assert llm.timeouts_seen == [12.5]
    assert llm.max_tokens_seen == [600]


def _report(*, papers: list[RetrievedPaper]) -> EvidenceReport:
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
            readiness_note="reviewed.",
        ),
        papers=papers,
        disclaimer="This report is retrieval plus recorded evidence only.",
    )


def _paper_with_evidence(
    *,
    claim_text: str | None = "Semaglutide reduced body weight.",
    evidence_direction: str = "supports",
    limitations: list[str] | None = None,
) -> RetrievedPaper:
    intelligence = EvidenceIntelligence(
        schema_version=1,
        evidence_record_id="ev-1",
        claim_id=1,
        evidence_quality=EvidenceQuality(
            score=94,
            study_design_tier="randomized_controlled_trial",
            manually_reviewed=True,
            extraction_tier="manual",
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
        synthesis=["Evidence Quality: 94/100."],
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
        retrieval_snippet="semaglutide reduced body weight",
        why_matched="Matched indexed title, abstract, or body text using: semaglutide",
        citation="A Trial of Semaglutide. (2026).",
        evidence_records=[
            EvidenceRecord(
                evidence_record_id="ev-1",
                extraction_method="manual_human_review",
                extraction_status="draft_manual_prototype",
                review_status="reviewed",
                review_checklist=None,
                review_notes=None,
                evidence_direction=evidence_direction,
                research_question=None,
                claim_text=claim_text,
                population=None,
                intervention=None,
                comparator=None,
                outcome=None,
                result_summary="Body weight reduced by 10.2% versus 1.5% with placebo.",
                limitations=[] if limitations is None else limitations,
                uncertainty_notes=None,
                confidence_note=None,
                source_span=None,
                evidence_intelligence=intelligence,
            )
        ],
    )


def test_build_synthesis_prompt_includes_evidence_record_id_and_claim_text() -> None:
    report = _report(papers=[_paper_with_evidence()])

    prompt = build_synthesis_prompt(report)

    assert "does semaglutide reduce body weight" in prompt
    assert "[ev-1]" in prompt
    assert "Semaglutide reduced body weight." in prompt
    assert "Body weight reduced by 10.2%" in prompt
    assert "Claim Confidence: 89/100" in prompt
    assert "Evidence direction: supports" in prompt
    assert "cite" in prompt.lower()


def test_build_synthesis_prompt_makes_qualifiers_and_limitations_explicit() -> None:
    report = _report(
        papers=[
            _paper_with_evidence(
                evidence_direction="qualifies",
                limitations=["Follow-up was limited to two years."],
            )
        ]
    )

    prompt = build_synthesis_prompt(report)

    assert "MUST address every evidence item labeled qualifies or contradicts" in prompt
    assert "Evidence direction: qualifies" in prompt
    assert "Limitations: Follow-up was limited to two years." in prompt


def test_build_synthesis_prompt_skips_records_without_claim_text() -> None:
    report = _report(papers=[_paper_with_evidence(claim_text=None)])

    prompt = build_synthesis_prompt(report)

    assert "ev-1" not in prompt
    assert "Answer:" in prompt  # still well-formed with an empty evidence section


def test_synthesize_answer_calls_the_llm_with_the_grounded_prompt() -> None:
    report = _report(papers=[_paper_with_evidence()])
    llm = _FakeLLM(response="Semaglutide reduces body weight [ev-1].")

    answer = synthesize_answer(report, llm)

    assert answer == "Semaglutide reduces body weight [ev-1]."
    assert len(llm.prompts) == 1
    assert "[ev-1]" in llm.prompts[0]


def test_synthesize_answer_returns_none_without_calling_the_llm_when_no_evidence() -> None:
    report = _report(papers=[])
    llm = _FakeLLM()

    answer = synthesize_answer(report, llm)

    assert answer is None
    assert llm.prompts == []


def test_synthesize_answer_returns_none_when_no_record_has_claim_text() -> None:
    report = _report(papers=[_paper_with_evidence(claim_text=None)])
    llm = _FakeLLM()

    answer = synthesize_answer(report, llm)

    assert answer is None
    assert llm.prompts == []
