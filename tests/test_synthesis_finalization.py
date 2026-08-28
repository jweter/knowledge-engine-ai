"""Regression coverage for release-safe synthesis finalization."""

from __future__ import annotations

from knowledge_engine_ai.llm import LocalLLMTimeoutError
from knowledge_engine_ai.models import (
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.verification import verify_synthesis
from knowledge_engine_ai.synthesis import synthesize_answer


class _LLM:
    def __init__(self, response: str | None = None, *, timeout: bool = False) -> None:
        self.response = response
        self.timeout = timeout

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del prompt, max_tokens, timeout_seconds
        if self.timeout:
            raise LocalLLMTimeoutError("bounded local generation timed out")
        assert self.response is not None
        return self.response


def _record(
    evidence_record_id: str,
    *,
    claim_text: str,
    result_summary: str,
    evidence_direction: str = "supports",
    limitations: list[str] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_record_id=evidence_record_id,
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
        result_summary=result_summary,
        limitations=[] if limitations is None else limitations,
        uncertainty_notes=None,
        confidence_note=None,
        source_span=None,
        evidence_intelligence=None,
    )


def _report() -> EvidenceReport:
    return EvidenceReport(
        schema_version=1,
        question="does music improve exercise endurance",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=2,
            draft=0,
            reviewed=2,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="reviewed.",
        ),
        papers=[
            RetrievedPaper(
                rank=1,
                paper_id=42,
                title="Music and endurance",
                authors="A. Author",
                year="2026",
                journal="A Journal",
                doi="10.1000/music",
                source_url="https://example.org",
                license_type="CC BY",
                metadata_source="sources.csv",
                retrieval_score=-5.1,
                retrieval_snippet="music endurance",
                why_matched="Matched indexed evidence.",
                citation="Music and endurance. (2026).",
                evidence_records=[
                    _record(
                        "ev-support",
                        claim_text="Music improved time to exhaustion.",
                        result_summary="Time to exhaustion improved by 8%.",
                    ),
                    _record(
                        "ev-qualifier",
                        claim_text="The observed effect was heterogeneous across protocols.",
                        result_summary="The benefit was not consistent across exercise protocols.",
                        evidence_direction="qualifies",
                        limitations=["Follow-up was limited to 2 sessions."],
                    ),
                ],
            )
        ],
        disclaimer="This report is retrieval plus recorded evidence only.",
    )


def test_timeout_returns_deterministic_grounded_fallback_that_passes_verification() -> None:
    report = _report()

    answer = synthesize_answer(report, _LLM(timeout=True), timeout_seconds=1.0)

    assert answer is not None
    assert "[ev-support]" in answer
    assert "[ev-qualifier]" in answer
    assert "Time to exhaustion improved by 8%." in answer
    assert "Follow-up was limited to 2 sessions." in answer
    assert verify_synthesis(answer, report).is_clean


def test_completely_uncited_model_output_is_discarded_for_grounded_fallback() -> None:
    report = _report()
    unsupported = "Music definitely improves endurance in every healthy adult."

    answer = synthesize_answer(report, _LLM(unsupported))

    assert answer is not None
    assert unsupported not in answer
    assert "[ev-support]" in answer
    assert "[ev-qualifier]" in answer
    assert verify_synthesis(answer, report).is_clean


def test_missing_qualifier_is_appended_from_the_exact_evidence_record() -> None:
    report = _report()

    answer = synthesize_answer(report, _LLM("Music improved endurance [ev-support]."))

    assert answer is not None
    assert answer.startswith("Music improved endurance [ev-support].")
    assert "Evidence qualifications and limitations:" in answer
    assert "[ev-qualifier]" in answer
    assert "Follow-up was limited to 2 sessions." in answer
    assert verify_synthesis(answer, report).is_clean


def test_hallucinated_only_citations_are_not_repaired_away() -> None:
    report = _report()
    hallucinated = "Music improved endurance [ev-does-not-exist]."

    answer = synthesize_answer(report, _LLM(hallucinated))

    assert answer == hallucinated
    verification = verify_synthesis(answer, report)
    assert verification.hallucinated_citations == ("ev-does-not-exist",)
    assert verification.is_clean is False


def test_numeric_limitation_is_grounded_because_synthesis_prompt_exposes_limitations() -> None:
    report = _report()
    narrative = (
        "Music improved time to exhaustion [ev-support]. "
        "Follow-up was limited to 2 sessions [ev-qualifier]."
    )

    verification = verify_synthesis(narrative, report)

    assert verification.ungrounded_numbers == ()
    assert verification.missed_qualifiers == ()
