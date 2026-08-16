"""Deterministic golden-question retrieval benchmark contracts.

This module measures retrieval against reviewed cross-domain expectations. It
never asks a model to decide relevance and never changes Core evidence state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenQuestion:
    """One fixed benchmark question and its reviewed retrieval expectations."""

    question_id: str
    domain: str
    question: str
    required_evidence_ids: tuple[str, ...]
    qualifier_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.question_id.strip():
            raise ValueError("Golden question ID must not be blank.")
        if not self.domain.strip():
            raise ValueError("Golden question domain must not be blank.")
        if not self.question.strip():
            raise ValueError("Golden question text must not be blank.")
        if not self.required_evidence_ids:
            raise ValueError("Golden question requires at least one expected evidence record.")
        if len(self.required_evidence_ids) != len(set(self.required_evidence_ids)):
            raise ValueError("Golden question required evidence IDs must be unique.")
        if len(self.qualifier_evidence_ids) != len(set(self.qualifier_evidence_ids)):
            raise ValueError("Golden question qualifier evidence IDs must be unique.")
        unknown_qualifiers = set(self.qualifier_evidence_ids) - set(self.required_evidence_ids)
        if unknown_qualifiers:
            raise ValueError("Qualifier evidence IDs must also be required evidence IDs.")


@dataclass(frozen=True)
class RetrievalBenchmarkResult:
    """Measured retrieval quality for one golden question."""

    question_id: str
    retrieved_evidence_ids: tuple[str, ...]
    required_found: tuple[str, ...]
    required_missing: tuple[str, ...]
    qualifier_found: tuple[str, ...]
    qualifier_missing: tuple[str, ...]
    recall_at_k: float
    qualifier_recall_at_k: float | None

    @property
    def passes_required_recall(self) -> bool:
        """Return true only when every required record was retrieved."""

        return not self.required_missing

    @property
    def passes_qualifier_recall(self) -> bool:
        """Return true when all expected qualifiers were retrieved."""

        return not self.qualifier_missing

    @property
    def passes(self) -> bool:
        """Return the conservative benchmark verdict."""

        return self.passes_required_recall and self.passes_qualifier_recall


def evaluate_retrieval(
    question: GoldenQuestion,
    retrieved_evidence_ids: tuple[str, ...],
    *,
    k: int | None = None,
) -> RetrievalBenchmarkResult:
    """Measure deterministic evidence-record recall in ranked retrieval order."""

    if k is not None and k < 1:
        raise ValueError("Benchmark k must be positive when provided.")

    ranked = retrieved_evidence_ids if k is None else retrieved_evidence_ids[:k]
    ranked_unique = tuple(dict.fromkeys(ranked))
    ranked_set = set(ranked_unique)

    required_found = tuple(
        evidence_id for evidence_id in question.required_evidence_ids if evidence_id in ranked_set
    )
    required_missing = tuple(
        evidence_id
        for evidence_id in question.required_evidence_ids
        if evidence_id not in ranked_set
    )
    qualifier_found = tuple(
        evidence_id for evidence_id in question.qualifier_evidence_ids if evidence_id in ranked_set
    )
    qualifier_missing = tuple(
        evidence_id
        for evidence_id in question.qualifier_evidence_ids
        if evidence_id not in ranked_set
    )

    recall = len(required_found) / len(question.required_evidence_ids)
    qualifier_recall = (
        len(qualifier_found) / len(question.qualifier_evidence_ids)
        if question.qualifier_evidence_ids
        else None
    )

    return RetrievalBenchmarkResult(
        question_id=question.question_id,
        retrieved_evidence_ids=ranked_unique,
        required_found=required_found,
        required_missing=required_missing,
        qualifier_found=qualifier_found,
        qualifier_missing=qualifier_missing,
        recall_at_k=recall,
        qualifier_recall_at_k=qualifier_recall,
    )


def default_golden_questions() -> tuple[GoldenQuestion, ...]:
    """Return the first reviewed cross-domain benchmark bank."""

    return (
        GoldenQuestion(
            question_id="glp1-body-weight",
            domain="glp1",
            question=(
                "Do GLP-1 receptor agonists reduce body weight in adults with "
                "overweight or obesity?"
            ),
            required_evidence_ids=(
                "ev-glp1-step5-body-weight-week104-001",
                "ev-glp1-select-trial-weight-loss-208wk-001",
                "ev-glp1-gao-meta-analysis-body-weight-001",
                "ev-glp1-step1-withdrawal-weight-regain-001",
                "ev-glp1-gao-meta-analysis-safety-discontinuation-001",
            ),
            qualifier_evidence_ids=(
                "ev-glp1-step1-withdrawal-weight-regain-001",
                "ev-glp1-gao-meta-analysis-safety-discontinuation-001",
            ),
        ),
        GoldenQuestion(
            question_id="oncology-nsclc-ici-os",
            domain="oncology",
            question=(
                "Do immune checkpoint inhibitors improve overall survival in adults "
                "with advanced non-small-cell lung cancer?"
            ),
            required_evidence_ids=(
                "ev-oncology-dang-2026-icichemo-vs-chemo-os-001",
                "ev-oncology-wu-2026-liver-mets-network-meta-pfs-os-001",
                "ev-oncology-katsarolis-2026-greek-realworld-os-001",
                "ev-oncology-weber-2026-nic-vs-pc-realworld-001",
            ),
            qualifier_evidence_ids=("ev-oncology-weber-2026-nic-vs-pc-realworld-001",),
        ),
        GoldenQuestion(
            question_id="mental-health-mdd-ssri-snri",
            domain="mental_health",
            question=(
                "Do SSRIs and SNRIs reduce depressive symptom severity in adults "
                "with major depressive disorder?"
            ),
            required_evidence_ids=(
                "ev-mh-yin-2023-escitalopram-vs-other-antidepressants-meta-001",
                "ev-mh-kishi-2024-japan-older-adults-meta-001",
                "ev-mh-perez-2025-depre5-second-line-strategies-001",
                "ev-mh-ju-2025-agomelatine-adjunctive-ssri-snri-rct-001",
            ),
            qualifier_evidence_ids=("ev-mh-ju-2025-agomelatine-adjunctive-ssri-snri-rct-001",),
        ),
    )
