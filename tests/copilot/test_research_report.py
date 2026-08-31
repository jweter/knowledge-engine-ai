from __future__ import annotations

import json

import pytest

from knowledge_engine_ai.copilot.progress_report import (
    ProviderStatusSummary,
    ResearchProgressReport,
    ResearchProgressStage,
)
from knowledge_engine_ai.copilot.research_report import (
    EvidenceDirectness,
    ReportCertainty,
    ResearchReportError,
    build_research_report_prompt,
    generate_research_report,
    parse_research_report_proposal,
)
from knowledge_engine_ai.copilot.research_state import ResearchState
from knowledge_engine_ai.models import (
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.bottleneck_report import (
    ResearchPipelineStage,
    SessionBottleneckReport,
)


class _FakeLLM:
    def __init__(self, output: str) -> None:
        self.output = output
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del max_tokens, timeout_seconds
        self.prompts.append(prompt)
        return self.output


def _record(
    record_id: str,
    *,
    direction: str = "supports",
    limitations: tuple[str, ...] = (),
    claim: str = "Systolic blood pressure increased after consumption.",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_record_id=record_id,
        extraction_method="llm-grounded-extraction-v1",
        extraction_status="complete",
        review_status="reviewed",
        review_checklist={},
        review_notes=None,
        evidence_direction=direction,
        research_question="Does the exposure increase blood pressure?",
        claim_text=claim,
        population="healthy adults",
        intervention="energy drink",
        comparator="control",
        outcome="blood pressure",
        result_summary=claim,
        limitations=list(limitations),
        uncertainty_notes=None,
        confidence_note=None,
        source_span={"page_number": 1},
    )


def _evidence_report() -> EvidenceReport:
    paper = RetrievedPaper(
        rank=1,
        paper_id=1,
        title="Energy drink blood pressure trial",
        authors="A. Researcher",
        year="2026",
        journal="Journal",
        doi="10.1/example",
        source_url="https://example.org/paper",
        license_type="CC BY",
        metadata_source="test",
        retrieval_score=1.0,
        retrieval_snippet="blood pressure",
        why_matched="matched blood pressure",
        citation="Researcher A. Energy drink blood pressure trial. 2026.",
        evidence_records=[
            _record("ev-positive"),
            _record(
                "ev-null",
                direction="contradicts",
                claim="Repeated exposure did not show a sustained blood-pressure increase.",
            ),
        ],
    )
    return EvidenceReport(
        schema_version=1,
        question="Does the exposure increase blood pressure?",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=2,
            draft=0,
            reviewed=2,
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
        question="Does the exposure increase blood pressure?",
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
        current_stage=ResearchPipelineStage.RERETRIEVAL,
        research_state=ResearchState.RESEARCHED_ANSWER,
        research_state_reason="grounded_reretrieval_releaseable",
        final=True,
        answer_available=True,
        wait_reason=None,
        elapsed_ms=100,
        indexed_evidence_record_ids=("ev-positive",),
        newly_acquired_evidence_record_ids=("ev-null",),
        provider_coverage_attempted=True,
        provider_coverage_completeness="partial",
        provider_degraded=True,
        provider_statuses=(
            ProviderStatusSummary(
                provider="pubmed",
                attempted=True,
                outcome="success",
                reason=None,
            ),
            ProviderStatusSummary(
                provider="openalex",
                attempted=True,
                outcome="degraded",
                reason="rate_limited",
            ),
        ),
        citations=(),
        unresolved_citations=(),
        limitations=("Short follow-up.",),
        bottleneck_report=bottleneck,
    )


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "bottom_line": (
            "Acute blood-pressure elevation is supported [ev-positive], while repeated-use "
            "evidence includes a null finding [ev-null]."
        ),
        "conclusion_rows": [
            {
                "question_dimension": "acute_bp",
                "conclusion": "Acute blood pressure can rise after exposure [ev-positive].",
                "certainty": "moderate",
                "certainty_rationale": (
                    "The retrieved direct trial supports the acute effect [ev-positive]."
                ),
                "supporting_evidence_ids": ["ev-positive"],
                "contradicting_or_null_evidence_ids": [],
                "directness": "direct",
                "missing_direct_evidence": None,
            },
            {
                "question_dimension": "habitual_bp",
                "conclusion": (
                    "Sustained elevation is not established by this evidence [ev-null]."
                ),
                "certainty": "low",
                "certainty_rationale": (
                    "The repeated-use result is null and coverage is limited [ev-null]."
                ),
                "supporting_evidence_ids": [],
                "contradicting_or_null_evidence_ids": ["ev-null"],
                "directness": "class_level",
                "missing_direct_evidence": "Long-duration direct exposure evidence is missing.",
            },
        ],
        "narrative_sections": [
            {
                "heading": "What the evidence separates",
                "body": (
                    "Acute and habitual effects should not be collapsed "
                    "[ev-positive] [ev-null]."
                ),
            }
        ],
        "missing_evidence": ["Long-duration direct exposure evidence."],
        "direct_evidence_summary": "The direct trial supports an acute effect [ev-positive].",
        "indirect_evidence_summary": "Repeated-use evidence includes a null result [ev-null].",
    }


def test_prompt_preserves_requested_answer_dimensions_and_evidence_boundaries() -> None:
    prompt = build_research_report_prompt(
        "Does the exposure increase blood pressure?",
        _evidence_report(),
        answer_dimensions=("acute_bp", "habitual_bp"),
    )

    assert "Use exactly these question_dimension values" in prompt
    assert "- acute_bp" in prompt
    assert "- habitual_bp" in prompt
    assert "id=ev-positive" in prompt
    assert "id=ev-null" in prompt
    assert "Acute evidence must not be phrased as proof" in prompt


def test_parse_requires_exact_dimensions_and_counter_evidence_coverage() -> None:
    proposal = parse_research_report_proposal(
        _payload(),
        known_evidence_ids=frozenset({"ev-positive", "ev-null"}),
        required_dimensions=("acute_bp", "habitual_bp"),
        required_counter_evidence_ids=frozenset({"ev-null"}),
    )

    assert proposal.conclusion_rows[0].certainty is ReportCertainty.MODERATE
    assert proposal.conclusion_rows[0].directness is EvidenceDirectness.DIRECT
    assert proposal.conclusion_rows[1].contradicting_or_null_evidence_ids == ("ev-null",)


def test_parse_rejects_unknown_evidence_identity() -> None:
    payload = _payload()
    rows = payload["conclusion_rows"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    row["supporting_evidence_ids"] = ["ev-invented"]

    with pytest.raises(ResearchReportError, match="unknown evidence ID"):
        parse_research_report_proposal(
            payload,
            known_evidence_ids=frozenset({"ev-positive", "ev-null"}),
        )


def test_parse_rejects_omitted_required_counter_evidence() -> None:
    payload = _payload()
    rows = payload["conclusion_rows"]
    assert isinstance(rows, list)
    row = rows[1]
    assert isinstance(row, dict)
    row["contradicting_or_null_evidence_ids"] = []

    with pytest.raises(ResearchReportError, match="omitted required qualifying/counter-evidence"):
        parse_research_report_proposal(
            payload,
            known_evidence_ids=frozenset({"ev-positive", "ev-null"}),
            required_counter_evidence_ids=frozenset({"ev-null"}),
        )


def test_generate_report_attaches_only_deterministic_progress_provenance() -> None:
    llm = _FakeLLM(json.dumps(_payload()))

    report = generate_research_report(
        "Does the exposure increase blood pressure?",
        _evidence_report(),
        _progress_report(),
        llm,
        answer_dimensions=("acute_bp", "habitual_bp"),
    )

    assert report.session_id == "session-1"
    assert report.research_state == "researched_answer"
    assert report.indexed_before_run_evidence_ids == ("ev-positive",)
    assert report.acquired_during_run_evidence_ids == ("ev-null",)
    assert report.degraded_providers == ("openalex",)
    assert report.provider_coverage_completeness == "partial"
    assert report.limitations == ("Short follow-up.",)
    serialized = report.to_dict()
    serialized_rows = serialized["conclusion_rows"]
    assert isinstance(serialized_rows, list)
    first_row = serialized_rows[0]
    assert isinstance(first_row, dict)
    assert first_row["certainty"] == "moderate"
    assert len(llm.prompts) == 1


def test_generate_report_rejects_model_output_without_json() -> None:
    llm = _FakeLLM("I cannot provide JSON.")

    with pytest.raises(ResearchReportError, match="no complete JSON object"):
        generate_research_report(
            "Does the exposure increase blood pressure?",
            _evidence_report(),
            _progress_report(),
            llm,
        )
