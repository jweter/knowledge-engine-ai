from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.models import (
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.retrieval_benchmark import GoldenQuestion
from knowledge_engine_ai.retrieval_benchmark_runner import (
    BenchmarkCorpus,
    ranked_evidence_ids,
    run_golden_benchmark,
)


def _record(evidence_record_id: str | None) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_record_id=evidence_record_id,
        extraction_method=None,
        extraction_status=None,
        review_status=None,
        review_checklist=None,
        review_notes=None,
        evidence_direction=None,
        research_question=None,
        claim_text=None,
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


def _paper(rank: int, *evidence_record_ids: str | None) -> RetrievedPaper:
    return RetrievedPaper(
        rank=rank,
        paper_id=rank,
        title=f"Paper {rank}",
        authors="",
        year="2026",
        journal="",
        doi="",
        source_url="",
        license_type="",
        metadata_source="",
        retrieval_score=1.0,
        retrieval_snippet="",
        why_matched="",
        citation="",
        evidence_records=[_record(item) for item in evidence_record_ids],
    )


def _report(*papers: RetrievedPaper) -> EvidenceReport:
    return EvidenceReport(
        schema_version=1,
        question="Does it work?",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=0,
            draft=0,
            reviewed=0,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="",
        ),
        papers=list(papers),
        disclaimer="",
    )


def test_ranked_evidence_ids_uses_paper_rank_and_skips_missing_ids() -> None:
    report = _report(
        _paper(2, "ev-c", None),
        _paper(1, "ev-a", "ev-b"),
    )

    assert ranked_evidence_ids(report) == ("ev-a", "ev-b", "ev-c")


def test_run_golden_benchmark_calls_core_retrieval_and_scores_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="test",
        question="Does it work?",
        required_evidence_ids=("ev-a", "ev-b"),
        qualifier_evidence_ids=("ev-b",),
    )
    calls: list[tuple[str, Path, Path, int, str]] = []

    def fake_evidence_report(
        question_text: str,
        *,
        sources: Path,
        evidence: Path,
        limit: int,
        ke_executable: str,
    ) -> EvidenceReport:
        calls.append((question_text, sources, evidence, limit, ke_executable))
        return _report(_paper(1, "ev-a", "ev-b"))

    monkeypatch.setattr(
        "knowledge_engine_ai.retrieval_benchmark_runner.evidence_report",
        fake_evidence_report,
    )

    suite = run_golden_benchmark(
        (question,),
        {"test": BenchmarkCorpus(Path("sources.csv"), Path("evidence.jsonl"))},
        limit=5,
        ke_executable="ke-test",
    )

    assert calls == [
        (
            "Does it work?",
            Path("sources.csv"),
            Path("evidence.jsonl"),
            5,
            "ke-test",
        )
    ]
    assert suite.limit == 5
    assert suite.runs[0].result.recall_at_k == 1.0
    assert suite.runs[0].result.qualifier_recall_at_k == 1.0
    assert suite.passes is True


def test_run_golden_benchmark_fails_conservatively_when_qualifier_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="test",
        question="Does it work?",
        required_evidence_ids=("ev-a", "ev-b"),
        qualifier_evidence_ids=("ev-b",),
    )

    def fake_evidence_report(
        question_text: str,
        *,
        sources: Path,
        evidence: Path,
        limit: int,
        ke_executable: str,
    ) -> EvidenceReport:
        del question_text, sources, evidence, limit, ke_executable
        return _report(_paper(1, "ev-a"))

    monkeypatch.setattr(
        "knowledge_engine_ai.retrieval_benchmark_runner.evidence_report",
        fake_evidence_report,
    )

    suite = run_golden_benchmark(
        (question,),
        {"test": BenchmarkCorpus(Path("sources.csv"), Path("evidence.jsonl"))},
    )

    assert suite.runs[0].result.required_missing == ("ev-b",)
    assert suite.runs[0].result.qualifier_missing == ("ev-b",)
    assert suite.passes is False


def test_run_golden_benchmark_requires_corpus_for_every_domain() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="missing",
        question="Does it work?",
        required_evidence_ids=("ev-a",),
    )

    with pytest.raises(ValueError, match="No benchmark corpus configured"):
        run_golden_benchmark((question,), {})


def test_run_golden_benchmark_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        run_golden_benchmark((), {}, limit=0)
