"""Typed models mirroring `core`'s `--format json` CLI contracts.

Parsed from the documented, versioned contracts `core`'s
`core_interface_contract.md` describes (`ke evidence-report --format
json` and `ke evidence-intelligence --format json`) -- never a raw dict
a caller has to string-key into, and never silently accepting a shape
this project does not recognize.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_EVIDENCE_INTELLIGENCE_SCHEMA_VERSION = 1


class EvidenceReportParseError(RuntimeError):
    """`ke evidence-report --format json`'s output did not match the expected shape."""


class EvidenceIntelligenceParseError(RuntimeError):
    """`ke evidence-intelligence --format json`'s output did not match the expected shape."""


@dataclass(frozen=True)
class EvidenceSummary:
    """Review-status counts for the evidence file consulted."""

    total: int
    draft: int
    reviewed: int
    needs_revision: int
    rejected: int
    unspecified: int
    readiness_note: str


@dataclass(frozen=True)
class EvidenceQuality:
    """One claim's Evidence Quality score, verbatim from `ke evidence-intelligence`."""

    score: int
    study_design_tier: str
    manually_reviewed: bool
    extraction_tier: str


@dataclass(frozen=True)
class EvidenceConsensus:
    """One claim's Evidence Consensus score, verbatim from `ke evidence-intelligence`."""

    relationship_edge_count: int
    supports_count: int
    contradicts_count: int
    agreement_total: int
    score: int | None
    reliability: str


@dataclass(frozen=True)
class ClaimConfidence:
    """One claim's Claim Confidence score, verbatim from `ke evidence-intelligence`."""

    score: int | None
    reliability: str


@dataclass(frozen=True)
class EvidenceCoverage:
    """Corpus-relative Evidence Coverage, verbatim from `ke evidence-intelligence`."""

    records_in_relationship: int
    total_records: int
    percentage: int


@dataclass(frozen=True)
class EvidenceIntelligence:
    """One claim's full Evidence Intelligence report, verbatim from `core` -- nothing re-derived.

    Parsed from `ke evidence-intelligence --format json`. Not part of
    `ke evidence-report`'s own JSON contract -- attached to an
    `EvidenceRecord` as a best-effort enrichment pass, `None` when the
    record has no graph claim yet (see `ke_client.evidence_intelligence`).
    Same three-numbers-never-collapsed discipline `core` enforces:
    `evidence_quality`, `evidence_consensus`, and `claim_confidence`
    always stay separate fields here too.
    """

    schema_version: int
    evidence_record_id: str
    claim_id: int
    evidence_quality: EvidenceQuality
    evidence_consensus: EvidenceConsensus
    claim_confidence: ClaimConfidence
    evidence_coverage: EvidenceCoverage
    synthesis: list[str]
    scope_note: str


@dataclass(frozen=True)
class EvidenceRecord:
    """One matched `EvidenceRecord`'s fields, verbatim from `core` -- nothing re-derived."""

    evidence_record_id: str | None
    extraction_method: str | None
    extraction_status: str | None
    review_status: str | None
    review_checklist: dict[str, Any] | None
    review_notes: str | None
    evidence_direction: str | None
    research_question: str | None
    claim_text: str | None
    population: str | None
    intervention: str | None
    comparator: str | None
    outcome: str | None
    result_summary: str | None
    limitations: list[str]
    uncertainty_notes: str | None
    confidence_note: str | None
    source_span: dict[str, Any] | None
    evidence_intelligence: EvidenceIntelligence | None = None


@dataclass(frozen=True)
class RetrievedPaper:
    """One ranked paper from lexical retrieval, plus any matched evidence records."""

    rank: int
    paper_id: int
    title: str
    authors: str
    year: str
    journal: str
    doi: str
    source_url: str
    license_type: str
    metadata_source: str
    retrieval_score: float
    retrieval_snippet: str
    why_matched: str
    citation: str
    evidence_records: list[EvidenceRecord]


@dataclass(frozen=True)
class EvidenceReport:
    """One `ke evidence-report --format json` response, fully parsed and typed."""

    schema_version: int
    question: str
    sources_path: str
    evidence_path: str
    evidence_summary: EvidenceSummary
    papers: list[RetrievedPaper]
    disclaimer: str


def parse_evidence_report(payload: dict[str, Any]) -> EvidenceReport:
    """Parse `ke evidence-report --format json`'s output into `EvidenceReport`.

    Raises `EvidenceReportParseError` on an unsupported `schema_version`
    or a missing required field -- never guesses a default for data
    `core` did not actually provide.
    """

    schema_version = payload.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise EvidenceReportParseError(
            f"Unsupported evidence-report schema_version: {schema_version!r} "
            f"(this project understands {SUPPORTED_SCHEMA_VERSION!r})."
        )

    try:
        summary_payload = payload["evidence_summary"]
        evidence_summary = EvidenceSummary(
            total=summary_payload["total"],
            draft=summary_payload["draft"],
            reviewed=summary_payload["reviewed"],
            needs_revision=summary_payload["needs_revision"],
            rejected=summary_payload["rejected"],
            unspecified=summary_payload["unspecified"],
            readiness_note=summary_payload["readiness_note"],
        )
        papers = [_parse_paper(paper_payload) for paper_payload in payload["papers"]]
        return EvidenceReport(
            schema_version=schema_version,
            question=payload["question"],
            sources_path=payload["sources_path"],
            evidence_path=payload["evidence_path"],
            evidence_summary=evidence_summary,
            papers=papers,
            disclaimer=payload["disclaimer"],
        )
    except KeyError as exc:
        raise EvidenceReportParseError(f"evidence-report JSON is missing field: {exc}") from exc


def parse_evidence_intelligence(payload: dict[str, Any]) -> EvidenceIntelligence:
    """Parse `ke evidence-intelligence --format json`'s output into `EvidenceIntelligence`.

    Raises `EvidenceIntelligenceParseError` on an unsupported
    `schema_version` or a missing required field -- never guesses a
    default for data `core` did not actually provide.
    """

    schema_version = payload.get("schema_version")
    if schema_version != SUPPORTED_EVIDENCE_INTELLIGENCE_SCHEMA_VERSION:
        raise EvidenceIntelligenceParseError(
            f"Unsupported evidence-intelligence schema_version: {schema_version!r} "
            f"(this project understands "
            f"{SUPPORTED_EVIDENCE_INTELLIGENCE_SCHEMA_VERSION!r})."
        )

    try:
        quality_payload = payload["evidence_quality"]
        consensus_payload = payload["evidence_consensus"]
        confidence_payload = payload["claim_confidence"]
        coverage_payload = payload["evidence_coverage"]
        return EvidenceIntelligence(
            schema_version=schema_version,
            evidence_record_id=payload["evidence_record_id"],
            claim_id=payload["claim_id"],
            evidence_quality=EvidenceQuality(
                score=quality_payload["score"],
                study_design_tier=quality_payload["study_design_tier"],
                manually_reviewed=quality_payload["manually_reviewed"],
                extraction_tier=quality_payload["extraction_tier"],
            ),
            evidence_consensus=EvidenceConsensus(
                relationship_edge_count=consensus_payload["relationship_edge_count"],
                supports_count=consensus_payload["supports_count"],
                contradicts_count=consensus_payload["contradicts_count"],
                agreement_total=consensus_payload["agreement_total"],
                score=consensus_payload["score"],
                reliability=consensus_payload["reliability"],
            ),
            claim_confidence=ClaimConfidence(
                score=confidence_payload["score"],
                reliability=confidence_payload["reliability"],
            ),
            evidence_coverage=EvidenceCoverage(
                records_in_relationship=coverage_payload["records_in_relationship"],
                total_records=coverage_payload["total_records"],
                percentage=coverage_payload["percentage"],
            ),
            synthesis=list(payload["synthesis"]),
            scope_note=payload["scope_note"],
        )
    except KeyError as exc:
        raise EvidenceIntelligenceParseError(
            f"evidence-intelligence JSON is missing field: {exc}"
        ) from exc


def _parse_paper(payload: dict[str, Any]) -> RetrievedPaper:
    try:
        return RetrievedPaper(
            rank=payload["rank"],
            paper_id=payload["paper_id"],
            title=payload["title"],
            authors=payload["authors"],
            year=payload["year"],
            journal=payload["journal"],
            doi=payload["doi"],
            source_url=payload["source_url"],
            license_type=payload["license_type"],
            metadata_source=payload["metadata_source"],
            retrieval_score=payload["retrieval_score"],
            retrieval_snippet=payload["retrieval_snippet"],
            why_matched=payload["why_matched"],
            citation=payload["citation"],
            evidence_records=[
                _parse_evidence_record(record_payload)
                for record_payload in payload["evidence_records"]
            ],
        )
    except KeyError as exc:
        raise EvidenceReportParseError(f"evidence-report paper is missing field: {exc}") from exc


def _parse_evidence_record(payload: dict[str, Any]) -> EvidenceRecord:
    limitations = payload.get("limitations")
    return EvidenceRecord(
        evidence_record_id=payload.get("evidence_record_id"),
        extraction_method=payload.get("extraction_method"),
        extraction_status=payload.get("extraction_status"),
        review_status=payload.get("review_status"),
        review_checklist=payload.get("review_checklist"),
        review_notes=payload.get("review_notes"),
        evidence_direction=payload.get("evidence_direction"),
        research_question=payload.get("research_question"),
        claim_text=payload.get("claim_text"),
        population=payload.get("population"),
        intervention=payload.get("intervention"),
        comparator=payload.get("comparator"),
        outcome=payload.get("outcome"),
        result_summary=payload.get("result_summary"),
        limitations=list(limitations) if isinstance(limitations, list) else [],
        uncertainty_notes=payload.get("uncertainty_notes"),
        confidence_note=payload.get("confidence_note"),
        source_span=payload.get("source_span"),
    )
