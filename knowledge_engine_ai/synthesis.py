"""LLM-grounded synthesis with deterministic evidence-safe release resilience.

The local LLM remains the preferred narrator, but release must not depend on a weak
model obeying citation instructions perfectly or finishing before the shared session
budget expires. Every deterministic fallback string in this module is assembled only
from fields Core already computed and grounded in the supplied ``EvidenceReport``.
Nothing discovered-but-unacquired, unreviewed, or outside the report may enter it.
"""

from __future__ import annotations

from collections.abc import Iterator

from knowledge_engine_ai.llm import LocalLLM, LocalLLMError
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


def build_synthesis_prompt(report: EvidenceReport) -> str:
    """Assemble the strict, evidence-only prompt for a local LLM."""

    evidence_blocks = list(_evidence_blocks(report.papers))
    mandatory_ids = _required_qualifier_ids(report)

    lines = [_SYSTEM_INSTRUCTIONS, "", f"Question: {report.question}"]
    if mandatory_ids:
        lines.extend(
            (
                "",
                "Mandatory qualification citations: "
                + ", ".join(f"[{item}]" for item in mandatory_ids),
                "The final answer is incomplete unless every mandatory citation above appears.",
            )
        )
    lines.extend(("", "Evidence:"))
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
    """Return a grounded answer while remaining useful when local narration degrades.

    The model is still preferred. If it fails, or returns text with no evidence citation
    at all, a deterministic evidence-only summary is returned instead. If the model
    cites evidence but omits a required qualifying/contradicting record or limitation,
    the missing Core-grounded material is appended deterministically. Verification is
    still responsible for the final release decision; this function does not bypass it.
    """

    if not _evidence_blocks(report.papers):
        return None

    prompt = build_synthesis_prompt(report)
    try:
        narrative = llm.generate(prompt, max_tokens=max_tokens, timeout_seconds=timeout_seconds)
    except LocalLLMError:
        return build_deterministic_evidence_summary(report)

    if not _cited_record_ids(narrative, report):
        return build_deterministic_evidence_summary(report)
    return _append_missing_qualifier_coverage(narrative, report)


def build_deterministic_evidence_summary(report: EvidenceReport) -> str | None:
    """Build a citation-complete evidence digest without asking a model to generate prose."""

    records = tuple(_claim_records(report))
    if not records:
        return None

    lines = [
        "Evidence-only summary (deterministic fallback):",
        "The following statements reproduce the grounded evidence available for this question.",
    ]
    for record in records:
        lines.extend(_record_summary_lines(record))
    return "\n".join(lines)


def _append_missing_qualifier_coverage(narrative: str, report: EvidenceReport) -> str:
    cited_ids = set(_cited_record_ids(narrative, report))
    missing = tuple(
        record
        for record in _claim_records(report)
        if _is_required_qualifier(record)
        and record.evidence_record_id is not None
        and record.evidence_record_id not in cited_ids
    )
    if not missing:
        return narrative

    lines = [narrative.rstrip(), "", "Required evidence qualifications:"]
    for record in missing:
        lines.extend(_record_summary_lines(record))
    return "\n".join(lines)


def _record_summary_lines(record: EvidenceRecord) -> list[str]:
    record_id = record.evidence_record_id
    if not record_id or not record.claim_text:
        return []
    citation = f"[{record_id}]"
    lines = [f"- {record.claim_text} {citation}"]
    if record.result_summary and record.result_summary.strip() != record.claim_text.strip():
        lines.append(f"  Reported result: {record.result_summary} {citation}")
    if record.evidence_direction in {"qualifies", "contradicts"}:
        lines.append(f"  Evidence direction: {record.evidence_direction}. {citation}")
    if record.limitations:
        lines.append(f"  Limitations: {'; '.join(record.limitations)}. {citation}")
    return lines


def _cited_record_ids(narrative: str, report: EvidenceReport) -> tuple[str, ...]:
    return tuple(
        record.evidence_record_id
        for record in _claim_records(report)
        if record.evidence_record_id is not None and f"[{record.evidence_record_id}]" in narrative
    )


def _required_qualifier_ids(report: EvidenceReport) -> tuple[str, ...]:
    return tuple(
        record.evidence_record_id
        for record in _claim_records(report)
        if record.evidence_record_id is not None and _is_required_qualifier(record)
    )


def _is_required_qualifier(record: EvidenceRecord) -> bool:
    return record.evidence_direction in {"qualifies", "contradicts"} or bool(record.limitations)


def _claim_records(report: EvidenceReport) -> Iterator[EvidenceRecord]:
    for paper in report.papers:
        for record in paper.evidence_records:
            if record.claim_text and record.evidence_record_id:
                yield record


def _evidence_blocks(papers: list[RetrievedPaper]) -> list[str]:
    blocks = []
    for paper in papers:
        for record in paper.evidence_records:
            if not record.claim_text or not record.evidence_record_id:
                continue
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
                    f"{confidence_score}/100"
                    if confidence_score is not None
                    else "not yet assessable"
                )
                block += (
                    f" Evidence Quality: {intelligence.evidence_quality.score}/100. "
                    f"Claim Confidence: {confidence_text} "
                    f"({intelligence.claim_confidence.reliability})."
                )
            blocks.append(block)
    return blocks
