"""Reproducible cross-domain retrieval baseline metadata.

This module binds the golden benchmark runner to Core's reviewed corpus layout
without copying scientific artifacts into AI. It also serializes measured
results with enough provenance to compare future ranking changes safely.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from knowledge_engine_ai.retrieval_benchmark_runner import (
    BenchmarkCorpus,
    GoldenBenchmarkSuite,
)

_CORE_CORPUS_DIRS = {
    "glp1": "glp1_weight_loss",
    "oncology": "oncology_nsclc_checkpoint_inhibitors",
    "mental_health": "mental_health_mdd_antidepressants",
}


def default_core_corpora(core_root: Path) -> dict[str, BenchmarkCorpus]:
    """Resolve the three reviewed benchmark corpora from a Core checkout."""

    corpora_root = core_root / "data" / "corpora"
    corpora: dict[str, BenchmarkCorpus] = {}
    for domain, directory_name in _CORE_CORPUS_DIRS.items():
        corpus_root = corpora_root / directory_name
        sources = corpus_root / "sources.csv"
        evidence = corpus_root / "evidence_records.jsonl"
        missing = [path for path in (sources, evidence) if not path.is_file()]
        if missing:
            missing_text = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(
                f"Core benchmark corpus for {domain!r} is incomplete; missing: {missing_text}"
            )
        corpora[domain] = BenchmarkCorpus(sources=sources, evidence=evidence)
    return corpora


def baseline_payload(
    suite: GoldenBenchmarkSuite,
    *,
    core_commit: str,
    ai_commit: str,
) -> dict[str, Any]:
    """Serialize one measured baseline with explicit repository provenance."""

    if not core_commit.strip():
        raise ValueError("Core commit must not be blank.")
    if not ai_commit.strip():
        raise ValueError("AI commit must not be blank.")

    return {
        "schema_version": 1,
        "core_commit": core_commit,
        "ai_commit": ai_commit,
        "retrieval_limit": suite.limit,
        "passes": suite.passes,
        "runs": [
            {
                "question_id": run.question.question_id,
                "domain": run.question.domain,
                "question": run.question.question,
                "required_evidence_ids": list(run.question.required_evidence_ids),
                "qualifier_evidence_ids": list(run.question.qualifier_evidence_ids),
                "result": asdict(run.result),
            }
            for run in suite.runs
        ],
    }
