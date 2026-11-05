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
