"""AI-O7: resolve a synthesized narrative's citations into sourced claims.

`docs/roadmap/future_ai_orchestration_plan.md`'s AI-O7 milestone: "Generate
a final report from validated structured objects. Success criterion: every
material scientific claim resolves to evidence IDs and source citations."
See `docs/ai_o7_design.md` for the full plan this module implements.

`synthesis.py` produces a narrative citing bare `[evidence_record_id]`
tokens; AI-O6's `verify_synthesis` checks those citations are real and
grounded. Neither resolves a citation into something a reader could
actually use to find the source. This module is that resolution step: it
joins each cited `evidence_record_id` up to the `RetrievedPaper` that
contains it, and assembles the paper-level bibliographic fields `ke
evidence-report` already computed -- no new data, no rewritten prose.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.verification import CITATION_PATTERN, VerificationResult


@dataclass(frozen=True)
class SourcedClaim:
    """One cited evidence record, resolved up to its paper's bibliographic fields."""

    evidence_record_id: str
    claim_text: str | None
    result_summary: str | None
    paper_title: str
    paper_authors: str
    paper_year: str
    paper_doi: str
    paper_citation: str
    paper_source_url: str


@dataclass(frozen=True)
class SessionReport:
    """A narrative plus every citation it made, resolved to a real source or flagged unresolved."""

    narrative: str
    sourced_claims: tuple[SourcedClaim, ...]
    unresolved_citations: tuple[str, ...]
    verification: VerificationResult

    @property
    def is_fully_sourced(self) -> bool:
        """True only when every citation the narrative made resolves to a real source."""

        return not self.unresolved_citations


def build_session_report(
    narrative: str, report: EvidenceReport, verification: VerificationResult
) -> SessionReport:
    """Resolve `narrative`'s citations against `report` using an already-computed `verification`.

    Does not call `verify_synthesis` itself -- `verification` is taken as
    a parameter so this step never recomputes what an earlier step
    already established. A citation repeated more than once in the
    narrative resolves to exactly one `SourcedClaim` (order of first
    appearance).
    """

    paper_by_record_id = {
        record.evidence_record_id: paper
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    }
    record_by_id = {
        record.evidence_record_id: record
        for paper in report.papers
        for record in paper.evidence_records
        if record.evidence_record_id
    }

    cited_ids = dict.fromkeys(CITATION_PATTERN.findall(narrative))

    sourced_claims = []
    for evidence_record_id in cited_ids:
        paper = paper_by_record_id.get(evidence_record_id)
        if paper is None:
            continue
        record = record_by_id[evidence_record_id]
        sourced_claims.append(
            SourcedClaim(
                evidence_record_id=evidence_record_id,
                claim_text=record.claim_text,
                result_summary=record.result_summary,
                paper_title=paper.title,
                paper_authors=paper.authors,
                paper_year=paper.year,
                paper_doi=paper.doi,
                paper_citation=paper.citation,
                paper_source_url=paper.source_url,
            )
        )

    return SessionReport(
        narrative=narrative,
        sourced_claims=tuple(sourced_claims),
        unresolved_citations=verification.hallucinated_citations,
        verification=verification,
    )
