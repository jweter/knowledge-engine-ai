from __future__ import annotations

import hashlib

import pytest

from knowledge_engine_ai.copilot.online_evidence_adapter import (
    ContentCheckedOnlineEvidence,
    OnlineCitation,
    OnlineClaim,
    OnlineExcerpt,
    OnlineSource,
)
from knowledge_engine_ai.copilot.online_report import (
    MAX_REPORT_CLAIMS,
    build_online_research_report,
)
from knowledge_engine_ai.copilot.research_report import ResearchReport


def _src(i: str, status: str = "retrieved") -> OnlineSource:
    ok = status == "retrieved"
    return OnlineSource(
        i, f"https://e.org/{i}", "p", "2026-01-01T00:00:00+00:00", status,
        hashlib.sha256(i.encode()).hexdigest() if ok else None,
        None if ok else "timeout", None,
    )  # fmt: skip


def _ev(
    claims: tuple[OnlineClaim, ...], extra: tuple[OnlineSource, ...] = ()
) -> ContentCheckedOnlineEvidence:
    return ContentCheckedOnlineEvidence(
        "Q?",
        (_src("a"), _src("b")) + extra,
        (OnlineExcerpt("a#1", "a", "x", None, None), OnlineExcerpt("b#1", "b", "y", None, None)),
        claims,
    )


def test_two_source_support_is_moderate_never_high() -> None:
    c = OnlineClaim(
        "c1",
        "T",
        "supported",
        (OnlineCitation("a#1", "supports"), OnlineCitation("b#1", "supports")),
    )
    r = build_online_research_report(_ev((c,)), search_run_id="run1")
    row = r.conclusion_rows[0]
    assert row.certainty.value == "moderate"
    assert row.supporting_evidence_ids == ("a#1", "b#1")
    assert r.research_state == "partial_answer" and r.session_id == "run1"
    assert r.acquired_during_run_evidence_ids == ("a#1", "b#1")
    assert row.missing_direct_evidence


def test_contested_single_source_and_empty_are_disclosed() -> None:
    contested = OnlineClaim(
        "c1",
        "T",
        "contested",
        (OnlineCitation("a#1", "supports"), OnlineCitation("b#1", "contradicts")),
    )
    single = OnlineClaim("c2", "U", "supported", (OnlineCitation("a#1", "supports"),))
    r = build_online_research_report(
        _ev((contested, single), (_src("z", "failed"),)), search_run_id="r"
    )
    assert [x.certainty.value for x in r.conclusion_rows] == ["low", "low"]
    assert r.conclusion_rows[0].contradicting_or_null_evidence_ids == ("b#1",)
    assert r.acquired_during_run_evidence_ids == ("a#1", "b#1")
    only_contra = OnlineClaim("c3", "V", "contradicted", (OnlineCitation("b#1", "contradicts"),))
    assert build_online_research_report(
        _ev((only_contra,)), search_run_id="r"
    ).acquired_during_run_evidence_ids == ("b#1",)
    assert any("Source z failed: timeout" in m for m in r.missing_evidence)
    empty = build_online_research_report(_ev(()), search_run_id="r")
    assert empty.research_state == "insufficient_evidence"
    assert any("no claims" in m for m in empty.missing_evidence)


def test_bounded_and_serializable_and_rejects_blank_run_id() -> None:
    claims = tuple(
        OnlineClaim(f"c{i}", "T", "insufficient_evidence", ()) for i in range(MAX_REPORT_CLAIMS + 3)
    )
    r = build_online_research_report(_ev(claims), search_run_id="r")
    assert len(r.conclusion_rows) == MAX_REPORT_CLAIMS
    assert r.conclusion_rows[0].certainty.value == "unavailable"
    assert any("3 claims omitted" in m for m in r.missing_evidence)
    assert '"schema_version": 1' in r.to_json()
    with pytest.raises(ValueError):
        build_online_research_report(_ev(()), search_run_id=" ")


def _provider_src(i: str, provider: str, status: str = "retrieved") -> OnlineSource:
    base = _src(i, status)
    return OnlineSource(
        base.source_id, base.url, provider, base.retrieved_at, base.status,
        base.content_sha256, base.failure_reason, base.title,
    )  # fmt: skip


def _cov(sources: tuple[OnlineSource, ...]) -> ResearchReport:
    return build_online_research_report(
        ContentCheckedOnlineEvidence("Q?", sources, (), ()), search_run_id="r"
    )


def test_full_provider_coverage_is_complete() -> None:
    r = _cov((_provider_src("a", "p1"), _provider_src("b", "p2")))
    assert r.provider_coverage_completeness == "complete"
    assert r.degraded_providers == ()
    assert [s.provider for s in r.provider_statuses] == ["p1", "p2"]


def test_partial_coverage_surfaces_degraded_provider_and_missing_evidence() -> None:
    r = _cov((_provider_src("a", "p1"), _provider_src("b", "p2", "failed")))
    assert r.provider_coverage_completeness == "partial"
    assert r.degraded_providers == ("p2",)
    assert any("Source b failed" in m for m in r.missing_evidence)
    assert r.provider_statuses[1].outcome == "failed"
    assert r.provider_statuses[1].reason == "timeout"


def test_all_providers_failed_is_none_coverage() -> None:
    r = _cov((_provider_src("a", "p1", "unavailable"),))
    assert r.provider_coverage_completeness == "none"
    assert r.degraded_providers == ("p1",)


def test_no_provider_data_stays_unavailable_not_fabricated() -> None:
    r = _cov(())
    assert r.provider_coverage_completeness is None
    assert r.degraded_providers == ()
    assert r.provider_statuses == ()
    assert any("unavailable" in x for x in r.limitations)
