from __future__ import annotations

import json
from dataclasses import dataclass

from knowledge_engine_ai.copilot.progress_report import (
    ResearchProgressReport,
    ResearchProgressStage,
)
from knowledge_engine_ai.copilot.research_report_integration import (
    build_research_report_for_result,
)
from knowledge_engine_ai.copilot.research_state import ResearchState
from knowledge_engine_ai.models import (
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.bottleneck_report import SessionBottleneckReport


class _FakeLLM:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del prompt, max_tokens, timeout_seconds
        self.calls += 1
        return self.output


@dataclass(frozen=True)
class _FakeResearchResult:
    question: str
    narrative_releaseable: bool
    effective_evidence_report: EvidenceReport | None
    progress_report: ResearchProgressReport | None


def _evidence_report() -> EvidenceReport:
    record = EvidenceRecord(
        evidence_record_id="ev-1",
        extraction_method="llm-grounded-extraction-v1",
        extraction_status="complete",
        review_status="reviewed",
        review_checklist={},
        review_notes=None,
        evidence_direction="supports",
        research_question="Does exposure change blood pressure?",
        claim_text="Blood pressure increased after exposure.",
        population="healthy adults",
        intervention="energy drink",
        comparator="control",
        outcome="blood pressure",
        result_summary="Blood pressure increased after exposure.",
        limitations=[],
        uncertainty_notes=None,
        confidence_note=None,
        source_span={"page_number": 1},
    )
    paper = RetrievedPaper(
        rank=1,
        paper_id=1,
        title="Trial",
        authors="A. Researcher",
        year="2026",
        journal="Journal",
        doi="10.1/example",
        source_url="https://example.org/trial",
        license_type="CC BY",
        metadata_source="test",
        retrieval_score=1.0,
        retrieval_snippet="blood pressure",
        why_matched="matched",
        citation="Researcher A. Trial. 2026.",
        evidence_records=[record],
    )
    return EvidenceReport(
        schema_version=1,
        question="Does exposure change blood pressure?",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=1,
            draft=0,
            reviewed=1,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="ready",
        ),
        papers=[paper],
        disclaimer="Evidence only.",
    )


def _progress_report() -> ResearchProgressReport:
    bottleneck = SessionBottleneckReport(
        session_id="session-1",
        question="Does exposure change blood pressure?",
        stages=(),
        event_count=0,
        timed_event_count=0,
        raw_event_duration_sum_ms=None,
        adjusted_known_duration_ms=None,
        parallel_overlap_adjustment_ms=0,
        slowest_stage=None,
        slowest_event=None,
        failed_event_ids=(),
        untimed_event_ids=(),
    )
    return ResearchProgressReport(
        schema_version=1,
        session_id="session-1",
        research_question_id="rq-1",
        progress_stage=ResearchProgressStage.FINAL_ANSWER,
        current_stage=None,
        research_state=ResearchState.INDEXED_ANSWER,
        research_state_reason="indexed_answer_releaseable",
        final=True,
        answer_available=True,
        wait_reason=None,
        elapsed_ms=20,
        indexed_evidence_record_ids=("ev-1",),
        newly_acquired_evidence_record_ids=(),
        provider_coverage_attempted=False,
        provider_coverage_completeness=None,
        provider_degraded=False,
        provider_statuses=(),
        citations=(),
        unresolved_citations=(),
        limitations=(),
        bottleneck_report=bottleneck,
    )


def _valid_model_output() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "bottom_line": "Blood pressure increased after exposure [ev-1].",
            "conclusion_rows": [
                {
                    "question_dimension": "blood_pressure_effect",
                    "conclusion": "The retrieved trial reports an increase [ev-1].",
                    "certainty": "moderate",
                    "certainty_rationale": "One grounded direct record is available [ev-1].",
                    "supporting_evidence_ids": ["ev-1"],
                    "contradicting_or_null_evidence_ids": [],
                    "directness": "direct",
                    "missing_direct_evidence": None,
                }
            ],
            "narrative_sections": [],
            "missing_evidence": [],
            "direct_evidence_summary": "One direct record reports an increase [ev-1].",
            "indirect_evidence_summary": "No indirect evidence is used.",
        }
    )


def test_releaseable_result_builds_structured_report() -> None:
    llm = _FakeLLM(_valid_model_output())
    result = _FakeResearchResult(
        question="Does exposure change blood pressure?",
        narrative_releaseable=True,
        effective_evidence_report=_evidence_report(),
        progress_report=_progress_report(),
    )

    built = build_research_report_for_result(
        result,
        llm,
        answer_dimensions=("blood_pressure_effect",),
    )

    assert built.available
    assert built.error_code is None
    assert built.report is not None
    assert built.report.session_id == "session-1"
    assert built.report.conclusion_rows[0].question_dimension == "blood_pressure_effect"
    assert llm.calls == 1


def test_nonreleaseable_result_never_calls_report_model() -> None:
    llm = _FakeLLM(_valid_model_output())
    result = _FakeResearchResult(
        question="Does exposure change blood pressure?",
        narrative_releaseable=False,
        effective_evidence_report=_evidence_report(),
        progress_report=_progress_report(),
    )

    built = build_research_report_for_result(result, llm)

    assert not built.available
    assert built.error_code == "base_answer_not_releaseable"
    assert llm.calls == 0


def test_missing_progress_report_fails_closed_without_model_call() -> None:
    llm = _FakeLLM(_valid_model_output())
    result = _FakeResearchResult(
        question="Does exposure change blood pressure?",
        narrative_releaseable=True,
        effective_evidence_report=_evidence_report(),
        progress_report=None,
    )

    built = build_research_report_for_result(result, llm)

    assert not built.available
    assert built.error_code == "progress_report_unavailable"
    assert llm.calls == 0


def test_malformed_structured_output_preserves_base_result_as_failure_code() -> None:
    llm = _FakeLLM("not json")
    result = _FakeResearchResult(
        question="Does exposure change blood pressure?",
        narrative_releaseable=True,
        effective_evidence_report=_evidence_report(),
        progress_report=_progress_report(),
    )

    built = build_research_report_for_result(result, llm)

    assert not built.available
    assert built.error_code == "research_report_generation_failed"
    assert llm.calls == 1
