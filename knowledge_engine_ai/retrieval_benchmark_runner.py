"""Run reviewed golden questions through Core's real retrieval seam.

This module deliberately stops at deterministic retrieval measurement. It does
not call synthesis, grade relevance with a model, mutate Core evidence, or
invent replacement confidence scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledge_engine_ai.ke_client import evidence_report
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.retrieval_benchmark import (
    GoldenQuestion,
    RetrievalBenchmarkResult,
    evaluate_retrieval,
)


@dataclass(frozen=True)
class BenchmarkCorpus:
    """Local Core inputs for one benchmark domain."""

    sources: Path
    evidence: Path


@dataclass(frozen=True)
class GoldenBenchmarkRun:
    """Measured result for one golden question against real Core retrieval."""

    question: GoldenQuestion
    result: RetrievalBenchmarkResult


@dataclass(frozen=True)
class GoldenBenchmarkSuite:
    """Cross-domain benchmark results from one fixed retrieval configuration."""

    limit: int
    runs: tuple[GoldenBenchmarkRun, ...]

    @property
    def passes(self) -> bool:
        """Return true only when every golden question passes conservatively."""

        return all(run.result.passes for run in self.runs)


def ranked_evidence_ids(report: EvidenceReport) -> tuple[str, ...]:
    """Extract Evidence Record IDs in Core's ranked paper/record order."""

    ranked: list[str] = []
    for paper in sorted(report.papers, key=lambda item: item.rank):
        for record in paper.evidence_records:
            if record.evidence_record_id:
                ranked.append(record.evidence_record_id)
    return tuple(ranked)


def run_golden_benchmark(
    questions: tuple[GoldenQuestion, ...],
    corpora: dict[str, BenchmarkCorpus],
    *,
    limit: int = 10,
    ke_executable: str = "ke",
    core_root: Path | None = None,
) -> GoldenBenchmarkSuite:
    """Run golden questions through ``ke evidence-report`` and score recall.

    ``core_root`` is the checkout whose local Core database should answer the
    benchmark. This matters because Core intentionally resolves its database
    from the CLI process working directory.
    """

    if limit < 1 or limit > 100:
        raise ValueError("Benchmark retrieval limit must be between 1 and 100.")

    runs: list[GoldenBenchmarkRun] = []
    for question in questions:
        try:
            corpus = corpora[question.domain]
        except KeyError as exc:
            raise ValueError(
                f"No benchmark corpus configured for domain {question.domain!r}."
            ) from exc

        report = evidence_report(
            question.question,
            sources=corpus.sources,
            evidence=corpus.evidence,
            limit=limit,
            ke_executable=ke_executable,
            working_directory=core_root,
        )
        result = evaluate_retrieval(
            question,
            ranked_evidence_ids(report),
            k=limit,
        )
        runs.append(GoldenBenchmarkRun(question=question, result=result))

    return GoldenBenchmarkSuite(limit=limit, runs=tuple(runs))
