"""Deterministic Research Report v1 projection over content-checked online evidence.

No LLM, corpus, or network access is used. Every row restates a Core claim and
its cited excerpt IDs; scientific certainty is unavailable because content checking
is not independent verification. The projection never invents a synthesized
answer, and it retains no source text (only IDs, claim text, and failure reasons).
"""

from __future__ import annotations

from knowledge_engine_ai.copilot.online_evidence_adapter import (
    ContentCheckedOnlineEvidence,
    OnlineClaim,
)
from knowledge_engine_ai.copilot.progress_report import ProviderStatusSummary
from knowledge_engine_ai.copilot.research_report import (
    RESEARCH_REPORT_SCHEMA_VERSION,
    ConclusionRow,
    EvidenceDirectness,
    NarrativeSection,
    ReportCertainty,
    ResearchReport,
)
from knowledge_engine_ai.copilot.research_state import ResearchState

MAX_REPORT_CLAIMS = 25
_NOT_ASSESSED = "Directness of the cited excerpts to the question was not assessed."


def _row(claim: OnlineClaim) -> ConclusionRow:
    # Keep each cited excerpt once per stance; repeating one citation must not
    # inflate support or counter-evidence in the rendered report.
    supporting = tuple(
        dict.fromkeys(c.excerpt_id for c in claim.citations if c.stance == "supports")
    )
    opposing = tuple(
        dict.fromkeys(c.excerpt_id for c in claim.citations if c.stance != "supports")
    )
    why = (
        "Scientific certainty unavailable: study quality, independence, "
        "directness and consistency have not been independently assessed."
    )
    return ConclusionRow(
        question_dimension=claim.claim_id,
        conclusion=f"[{claim.status}] {claim.text}",
        certainty=ReportCertainty.UNAVAILABLE,
        certainty_rationale=why,
        supporting_evidence_ids=supporting,
        contradicting_or_null_evidence_ids=opposing,
        directness=EvidenceDirectness.UNAVAILABLE,
        missing_direct_evidence=_NOT_ASSESSED,
    )


def _provider_coverage(
    evidence: ContentCheckedOnlineEvidence,
) -> tuple[str | None, tuple[str, ...], tuple[ProviderStatusSummary, ...], tuple[str, ...]]:
    """Derive coverage only from the per-source statuses Core reported.

    Returns (coverage completeness, degraded providers, source-derived statuses, limitations).
    Source retrieval cannot establish provider-search completeness.
    """
    if not evidence.sources:
        return None, (), (), ("Provider coverage unavailable: Core reported no sources.",)
    by_provider: dict[str, list[str]] = {}
    reasons: dict[str, str | None] = {}
    for s in evidence.sources:
        by_provider.setdefault(s.provider, []).append(s.status)
        if s.status != "retrieved" and s.provider not in reasons:
            reasons[s.provider] = s.failure_reason
    statuses = []
    for provider, found in by_provider.items():
        bad = next((x for x in found if x != "retrieved"), None)
        statuses.append(
            ProviderStatusSummary(provider, True, bad or "retrieved", reasons.get(provider))
        )
    degraded = tuple(s.provider for s in statuses if s.outcome != "retrieved")
    note = (
        "Provider search coverage unavailable: Core supplied only returned-source "
        "retrieval statuses, "
        "not the attempted-provider ledger or search completeness. Successful retrieval does not "
        "establish comprehensive coverage."
    )
    return None, degraded, tuple(statuses), (note,)


def build_online_research_report(
    evidence: ContentCheckedOnlineEvidence, *, search_run_id: str
) -> ResearchReport:
    """Project online evidence into the stable report contract, bounded and lossless on IDs."""
    if not isinstance(search_run_id, str) or not search_run_id.strip():
        raise ValueError("search_run_id must be non-empty text.")
    claims = evidence.claims[:MAX_REPORT_CLAIMS]
    rows = tuple(_row(c) for c in claims)
    missing: list[str] = [
        f"Source {s.source_id} {s.status}: {s.failure_reason}"
        for s in evidence.sources
        if s.status != "retrieved"
    ]
    if not evidence.claims:
        missing.append("Core supplied no claims for this question.")
    if len(evidence.claims) > MAX_REPORT_CLAIMS:
        missing.append(
            f"{len(evidence.claims) - MAX_REPORT_CLAIMS} claims omitted by the report bound."
        )
    supported = [r for r in rows if r.conclusion.startswith("[supported]")]
    state = ResearchState.PARTIAL_ANSWER if supported else ResearchState.INSUFFICIENT_EVIDENCE
    retrieved = sum(s.status == "retrieved" for s in evidence.sources)
    cited = tuple(
        dict.fromkeys(
            i
            for r in rows
            for i in (*r.supporting_evidence_ids, *r.contradicting_or_null_evidence_ids)
        )
    )
    completeness, degraded, statuses, coverage_notes = _provider_coverage(evidence)
    return ResearchReport(
        schema_version=RESEARCH_REPORT_SCHEMA_VERSION,
        question=evidence.question,
        bottom_line=(
            f"{len(supported)} of {len(rows)} claims have supporting citations from "
            f"{retrieved} of {len(evidence.sources)} sources; no synthesized answer was produced."
        ),
        conclusion_rows=rows,
        narrative_sections=(
            NarrativeSection(
                "Evidence boundary",
                "Excerpts matched their retrieved text and hashes; sources, providers, "
                "and scientific claims are not independently verified.",
            ),
        ),
        missing_evidence=tuple(missing),
        direct_evidence_summary="Directness was not assessed.",
        indirect_evidence_summary="Directness was not assessed.",
        provider_coverage_completeness=completeness,
        degraded_providers=degraded,
        provider_statuses=statuses,
        indexed_before_run_evidence_ids=(),
        acquired_during_run_evidence_ids=cited,
        limitations=(
            "Deterministic projection of Core claims; no LLM synthesis.",
            *coverage_notes,
        ),
        session_id=search_run_id,
        research_state=state.value,
    )
