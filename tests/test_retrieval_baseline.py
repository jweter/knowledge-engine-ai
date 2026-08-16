from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.retrieval_baseline import baseline_payload, default_core_corpora
from knowledge_engine_ai.retrieval_benchmark import GoldenQuestion, evaluate_retrieval
from knowledge_engine_ai.retrieval_benchmark_runner import (
    GoldenBenchmarkRun,
    GoldenBenchmarkSuite,
)


def _write_corpus(root: Path, name: str) -> None:
    corpus = root / "data" / "corpora" / name
    corpus.mkdir(parents=True)
    (corpus / "sources.csv").write_text("source_id,title\n", encoding="utf-8")
    (corpus / "evidence_records.jsonl").write_text("", encoding="utf-8")


def test_default_core_corpora_resolves_reviewed_three_domain_layout(tmp_path: Path) -> None:
    _write_corpus(tmp_path, "glp1_weight_loss")
    _write_corpus(tmp_path, "oncology_nsclc_checkpoint_inhibitors")
    _write_corpus(tmp_path, "mental_health_mdd_antidepressants")

    corpora = default_core_corpora(tmp_path)

    assert set(corpora) == {"glp1", "oncology", "mental_health"}
    assert corpora["glp1"].sources == (
        tmp_path / "data" / "corpora" / "glp1_weight_loss" / "sources.csv"
    )


def test_default_core_corpora_fails_when_required_artifact_is_missing(tmp_path: Path) -> None:
    _write_corpus(tmp_path, "glp1_weight_loss")
    _write_corpus(tmp_path, "oncology_nsclc_checkpoint_inhibitors")
    corpus = tmp_path / "data" / "corpora" / "mental_health_mdd_antidepressants"
    corpus.mkdir(parents=True)
    (corpus / "sources.csv").write_text("source_id,title\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="mental_health"):
        default_core_corpora(tmp_path)


def test_baseline_payload_records_repo_provenance_and_measured_ids() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="glp1",
        question="Does treatment help?",
        required_evidence_ids=("ev-a", "ev-b"),
        qualifier_evidence_ids=("ev-b",),
    )
    result = evaluate_retrieval(question, ("ev-a", "ev-b"), k=10)
    suite = GoldenBenchmarkSuite(
        limit=10,
        runs=(GoldenBenchmarkRun(question=question, result=result),),
    )

    payload = baseline_payload(suite, core_commit="core123", ai_commit="ai456")

    assert payload["schema_version"] == 1
    assert payload["core_commit"] == "core123"
    assert payload["ai_commit"] == "ai456"
    assert payload["retrieval_limit"] == 10
    assert payload["passes"] is True
    assert payload["runs"][0]["result"]["retrieved_evidence_ids"] == ("ev-a", "ev-b")


def test_baseline_payload_rejects_blank_commit_provenance() -> None:
    suite = GoldenBenchmarkSuite(limit=10, runs=())

    with pytest.raises(ValueError, match="Core commit"):
        baseline_payload(suite, core_commit=" ", ai_commit="ai456")
    with pytest.raises(ValueError, match="AI commit"):
        baseline_payload(suite, core_commit="core123", ai_commit="")
