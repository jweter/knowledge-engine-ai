"""Reproducible cross-domain retrieval baseline metadata.

This module binds the golden benchmark runner to Core's reviewed corpus layout
without copying scientific artifacts into AI. It also serializes measured
results with enough provenance to compare future ranking changes safely.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from knowledge_engine_ai.retrieval_benchmark import default_golden_questions
from knowledge_engine_ai.retrieval_benchmark_runner import (
    BenchmarkCorpus,
    GoldenBenchmarkSuite,
    run_golden_benchmark,
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


def git_commit(checkout_root: Path) -> str:
    """Resolve one checkout's exact commit without invoking a shell."""

    completed = subprocess.run(
        ["git", "-C", str(checkout_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not commit:
        raise ValueError("Could not resolve checkout commit for retrieval baseline provenance.")
    return commit


def git_clean_commit(checkout_root: Path) -> str:
    """Resolve a commit only when tracked files match that commit exactly."""

    completed = subprocess.run(
        ["git", "-C", str(checkout_root), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("Could not inspect checkout state for retrieval baseline provenance.")
    if completed.stdout.strip():
        raise ValueError(
            "Retrieval baseline provenance requires tracked files to match the recorded commit."
        )
    return git_commit(checkout_root)


def run_retrieval_baseline(
    *,
    core_root: Path,
    ai_root: Path,
    limit: int = 10,
    ke_executable: str = "ke",
) -> dict[str, Any]:
    """Run the reviewed three-domain benchmark and return its reproducible snapshot."""

    core_commit = git_clean_commit(core_root)
    ai_commit = git_clean_commit(ai_root)
    suite = run_golden_benchmark(
        default_golden_questions(),
        default_core_corpora(core_root),
        limit=limit,
        ke_executable=ke_executable,
        core_root=core_root,
    )
    return baseline_payload(
        suite,
        core_commit=core_commit,
        ai_commit=ai_commit,
    )
