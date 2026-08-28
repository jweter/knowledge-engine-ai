"""LLM-grounded synthesis with deterministic evidence-safe fallback coverage.

The local model may narrate only fields Core already computed and stood behind.
This module now also treats citation compliance as an executable contract rather
than prompt text alone: a completely uncited model response is discarded in favor
of a deterministic evidence rendering, and qualifying/contradicting evidence that
the model omitted is appended verbatim from the retrieved EvidenceRecords.

A bounded Ollama generation timeout is the one model failure that may use the same
deterministic fallback. Other local-model failures still propagate so outages,
missing models, malformed responses, and transport errors remain explicit rather
than being silently hidden.
"""

from __future__ import annotations

import re

from knowledge_engine_ai.llm import LocalLLM, LocalLLMTimeoutError
from knowledge_engine_ai.models import EvidenceRecord, EvidenceReport, RetrievedPaper

_SYSTEM_INSTRUCTIONS = (
    "You are a careful research assistant summarizing evidence for a clinician or researcher. "
    "Answer the question using ONLY the evidence listed below -- never add a fact, statistic, or "
    "claim that is not present in it. Cite the evidence_record_id in square brackets after every "
    "claim you state, e.g. [ev-example-001]. If the evidence is insufficient, contradictory, or "
    "absent, say so plainly instead of guessing. Do not invent a confidence score of your own; "
    "if a Claim Confidence number is given, you may mention it, but never compute a new one. "
    "You MUST address every evidence item labeled qualifies or contradicts and every listed "
    "limitation, citing that item's evidence_record_id. Do not present an overall conclusion "
    "without those qualification boundaries."
)

_CITATION_TOKEN_RE = re.compile(r"\[([A-Za-z0-9_\-]+)\]")
_QUALIFYING_DIRECTIONS = {"qualifies", "contradicts"}


def build_synthesis_prompt(report: EvidenceReport) -> str:
    """Assemble the strict, evidence-only prompt for a local LLM.

    Only records that actually have ``claim_text`` are included. A matched paper
    with zero usable evidence records contributes nothing to ground on, so it is
    left out rather than padding the prompt with retrieval metadata.
    """

    evidence_blocks = list(_evidence_blocks(report.papers))

    lines = [_SYSTEM_INSTRUCTIONS, "", f"Question: {report.question}", "", "Evidence:"]
    lines.extend(evidence_blocks)
    lines.append("")
    lines.append("Answer:")
    return "\n".join(lines)


def synthesize_answer(
    report: EvidenceReport,
    llm: LocalLLM,
    *,
    max_tokens: int = 600,
    timeout_seconds: float | None = None,
) -> str | None:
    """Return a grounded narrative answer, or ``None`` when no claim evidence exists.

    Citation safety is enforced after generation. A response with no citation tokens
    at all is not trusted as narrative and is replaced with a deterministic rendering
    of the retrieved evidence. A response containing only unknown citation IDs is
    deliberately *not* repaired; deterministic verification must see and block those
    hallucinated citations. Any omitted qualifying/contradicting record or record with
    limitations is appended directly from the report so the release gate cannot be
    bypassed by a small model ignoring the prompt.

    If Ollama merely runs out of its bounded generation time, the same deterministic
    evidence rendering is returned immediately. Other ``LocalLLMError`` subclasses
    are allowed to propagate so infrastructure/model failures remain observable.
    """

    records = _grounded_records(report.papers)
    if not records:
        return None

    prompt = build_synthesis_prompt(report)
    try:
        answer = llm.generate(prompt, max_tokens=max_tokens, timeout_seconds=timeout_seconds)
    except LocalLLMTimeoutError:
        return build_grounded_evidence_fallback(report)

    return ensure_required_evidence_coverage(answer, report)


def ensure_required_evidence_coverage(narrative: str, report: EvidenceReport) -> str:
    """Enforce citation and qualifier coverage without inventing new prose claims.

    Completely uncited free text is discarded. Hallucinated citation tokens are left
    untouched for the verifier to reject. When at least one real citation is present,
    any required qualifier the model omitted is appended from its exact EvidenceRecord.
    """

    records = _grounded_records(report.papers)
    if not records:
        return narrative

    cited_ids = tuple(dict.fromkeys(_CITATION_TOKEN_RE.findall(narrative)))
    if not cited_ids:
        fallback = build_grounded_evidence_fallback(report)
        return narrative if fallback is None else fallback

    known_ids = {record.evidence_record_id for record in records}
    cited_known_ids = {citation_id for citation_id in cited_ids if citation_id in known_ids}
    if not cited_known_ids:
        # Preserve hallucinated-only output so verify_synthesis can fail closed.
        return narrative

    missing_required = tuple(
        record
        for record in records
        if record.evidence_record_id not in cited_known_ids and _requires_explicit_coverage(record)
    )
    if not missing_required:
        return narrative

    lines = [narrative.rstrip(), "", "Evidence qualifications and limitations:"]
    lines.extend(f"- {_render_evidence_record(record)}" for record in missing_required)
    return "\n".join(lines)


def build_grounded_evidence_fallback(report: EvidenceReport) -> str | None:
    """Render retrieved claim evidence deterministically when free-text synthesis is unsafe."""

    records = _grounded_records(report.papers)
    if not records:
        return None

    lines = [
        "A citation-grounded synthesized narrative was not available within the bounded run. "
        "The retrieved evidence is presented directly:",
    ]
    lines.extend(f"- {_render_evidence_record(record)}" for record in records)
    return "\n".join(lines)


def _grounded_records(papers: list[RetrievedPaper]) -> tuple[EvidenceRecord, ...]:
    return tuple(
        record
        for paper in papers
        for record in paper.evidence_records
        if record.claim_text and record.evidence_record_id
    )


def _evidence_blocks(papers: list[RetrievedPaper]) -> list[str]:
    return [_render_evidence_record(record) for record in _grounded_records(papers)]


def _render_evidence_record(record: EvidenceRecord) -> str:
    assert record.evidence_record_id is not None
    assert record.claim_text is not None

    block = f"[{record.evidence_record_id}] {record.claim_text}"
    if record.evidence_direction:
        block += f" Evidence direction: {record.evidence_direction}."
    if record.result_summary:
        block += f" Result: {record.result_summary}"
    if record.limitations:
        block += f" Limitations: {'; '.join(record.limitations)}."
    intelligence = record.evidence_intelligence
    if intelligence is not None:
        confidence_score = intelligence.claim_confidence.score
        confidence_text = (
            f"{confidence_score}/100" if confidence_score is not None else "not yet assessable"
        )
        block += (
            f" Evidence Quality: {intelligence.evidence_quality.score}/100. "
            f"Claim Confidence: {confidence_text} "
            f"({intelligence.claim_confidence.reliability})."
        )
    return block


def _requires_explicit_coverage(record: EvidenceRecord) -> bool:
    return record.evidence_direction in _QUALIFYING_DIRECTIONS or bool(record.limitations)


__all__ = [
    "build_grounded_evidence_fallback",
    "build_synthesis_prompt",
    "ensure_required_evidence_coverage",
    "synthesize_answer",
]
