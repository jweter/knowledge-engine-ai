"""LLM-grounded synthesis: one narrative paragraph, strictly grounded in `report`.

The only place in this project a model-generated string is allowed to
appear (`docs/ai_design.md`'s "Decision: local LLM" section). The seam
still holds: the prompt this module builds contains nothing but fields
`core` already computed and stood behind elsewhere (`claim_text`,
`result_summary`, Evidence Quality/Consensus/Claim Confidence) -- the
model is told, explicitly, to use only that content and to cite each
claim's `evidence_record_id`, never to introduce a fact, a number, or a
confidence rating this project has not already computed. This is
narration of existing signals, not a new judgment.
"""

from __future__ import annotations

from knowledge_engine_ai.llm import LocalLLM
from knowledge_engine_ai.models import EvidenceReport, RetrievedPaper

_SYSTEM_INSTRUCTIONS = (
    "You are a careful research assistant summarizing evidence for a clinician or researcher. "
    "Answer the question using ONLY the evidence listed below -- never add a fact, statistic, or "
    "claim that is not present in it. Cite the evidence_record_id in square brackets after every "
    "claim you state, e.g. [ev-example-001]. If the evidence is insufficient, contradictory, or "
    "absent, say so plainly instead of guessing. Do not invent a confidence score of your own; "
    "if a Claim Confidence number is given, you may mention it, but never compute a new one."
)


def build_synthesis_prompt(report: EvidenceReport) -> str:
    """Assemble the strict, evidence-only prompt for a local LLM.

    Only records that actually have `claim_text` are included -- a
    matched paper with zero evidence records contributes nothing to
    ground on, so it is left out rather than padding the prompt with
    retrieval metadata the model has no evidence-based use for.
    """

    evidence_blocks = list(_evidence_blocks(report.papers))

    lines = [_SYSTEM_INSTRUCTIONS, "", f"Question: {report.question}", "", "Evidence:"]
    lines.extend(evidence_blocks)
    lines.append("")
    lines.append("Answer:")
    return "\n".join(lines)


def synthesize_answer(
    report: EvidenceReport, llm: LocalLLM, *, max_tokens: int = 400
) -> str | None:
    """Return a grounded narrative answer, or `None` if there is no evidence to ground on.

    Deliberately skips calling the model at all when zero evidence
    records have `claim_text` -- nothing to narrate, and asking a model
    to answer from an empty evidence list only invites it to guess.
    """

    if not _evidence_blocks(report.papers):
        return None

    prompt = build_synthesis_prompt(report)
    return llm.generate(prompt, max_tokens=max_tokens)


def _evidence_blocks(papers: list[RetrievedPaper]) -> list[str]:
    blocks = []
    for paper in papers:
        for record in paper.evidence_records:
            if not record.claim_text or not record.evidence_record_id:
                continue
            block = f"[{record.evidence_record_id}] {record.claim_text}"
            if record.result_summary:
                block += f" Result: {record.result_summary}"
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
