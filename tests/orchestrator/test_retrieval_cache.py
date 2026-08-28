"""BT-5a: bounded in-process cache for successful indexed retrieval results.

Covers the cache module's own identity/eviction rules plus
`parallel_retrieval.run_parallel_retrieval`'s integration of it: reuse
across repeated calls, automatic invalidation on evidence-content
change, "failures are never cached," and external discovery still
running independently of indexed-retrieval cache hits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knowledge_engine_ai.ke_client import KeCommandError
from knowledge_engine_ai.models import EvidenceReport, parse_evidence_report
from knowledge_engine_ai.orchestrator import parallel_retrieval
from knowledge_engine_ai.orchestrator.retrieval_cache import (
    clear_retrieval_cache,
    normalize_retrieval_query,
    retrieval_cache_size,
)


@pytest.fixture(autouse=True)
def _isolated_cache() -> Any:
    clear_retrieval_cache()
    yield
    clear_retrieval_cache()


def _report(question: str) -> EvidenceReport:
    return parse_evidence_report(
        {
            "schema_version": 1,
            "question": question,
            "sources_path": "sources.csv",
            "evidence_path": "evidence.jsonl",
            "evidence_summary": {
                "total": 0,
                "draft": 0,
                "reviewed": 0,
                "needs_revision": 0,
                "rejected": 0,
                "unspecified": 0,
                "readiness_note": "empty",
            },
            "papers": [],
            "disclaimer": "retrieval plus recorded evidence only",
        }
    )


def _indexed_files(tmp_path: Path) -> tuple[Path, Path]:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("paper_id,title\n1,Example\n", encoding="utf-8")
    evidence.write_text('{"evidence_record_id":"ev-1"}\n', encoding="utf-8")
    return sources, evidence


def test_normalize_retrieval_query_collapses_case_and_whitespace() -> None:
    assert normalize_retrieval_query("  Does   MUSIC Help? ") == "does music help?"


def test_repeated_parallel_retrieval_reuses_both_successful_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, evidence = _indexed_files(tmp_path)
    calls: list[str] = []

    def fake_report(query: str, **kwargs: object) -> EvidenceReport:
        calls.append(query)
        return _report(query)

    monkeypatch.setattr(parallel_retrieval, "enriched_evidence_report", fake_report)

    first = parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?", sources=sources, evidence=evidence
    )
    second = parallel_retrieval.run_parallel_retrieval(
        "  does MUSIC improve   endurance?  ", sources=sources, evidence=evidence
    )

    assert len(calls) == 2
    assert first.primary.cache_hit is False
    assert first.contradiction.cache_hit is False
    assert second.primary.cache_hit is True
    assert second.contradiction.cache_hit is True
    assert second.primary.report == first.primary.report


def test_evidence_content_change_invalidates_cached_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, evidence = _indexed_files(tmp_path)
    calls: list[str] = []

    def fake_report(query: str, **kwargs: object) -> EvidenceReport:
        calls.append(query)
        return _report(query)

    monkeypatch.setattr(parallel_retrieval, "enriched_evidence_report", fake_report)

    parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?", sources=sources, evidence=evidence
    )
    evidence.write_text(
        evidence.read_text(encoding="utf-8") + '{"evidence_record_id":"ev-2"}\n',
        encoding="utf-8",
    )
    changed = parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?", sources=sources, evidence=evidence
    )

    assert len(calls) == 4
    assert changed.primary.cache_hit is False
    assert changed.contradiction.cache_hit is False


def test_failed_retrieval_is_never_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources, evidence = _indexed_files(tmp_path)
    attempts: dict[str, int] = {}

    def flaky_report(query: str, **kwargs: object) -> EvidenceReport:
        attempts[query] = attempts.get(query, 0) + 1
        if attempts[query] == 1:
            raise KeCommandError("temporary retrieval failure")
        return _report(query)

    monkeypatch.setattr(parallel_retrieval, "enriched_evidence_report", flaky_report)

    first = parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?", sources=sources, evidence=evidence
    )
    second = parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?", sources=sources, evidence=evidence
    )
    third = parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?", sources=sources, evidence=evidence
    )

    assert first.primary.error is not None
    assert first.contradiction.error is not None
    assert second.primary.cache_hit is False
    assert second.contradiction.cache_hit is False
    assert third.primary.cache_hit is True
    assert third.contradiction.cache_hit is True
    assert set(attempts.values()) == {2}


def test_external_discovery_still_runs_when_indexed_retrieval_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, evidence = _indexed_files(tmp_path)
    discovery_calls: list[str] = []

    monkeypatch.setattr(
        parallel_retrieval,
        "enriched_evidence_report",
        lambda query, **kwargs: _report(query),
    )

    def discover(question: str) -> object:
        discovery_calls.append(question)
        return {"ok": True}

    parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?",
        sources=sources,
        evidence=evidence,
        external_discovery=discover,
    )
    cached = parallel_retrieval.run_parallel_retrieval(
        "Does music improve endurance?",
        sources=sources,
        evidence=evidence,
        external_discovery=discover,
    )

    assert cached.primary.cache_hit is True
    assert cached.contradiction.cache_hit is True
    assert discovery_calls == [
        "Does music improve endurance?",
        "Does music improve endurance?",
    ]


def test_cache_is_bounded_to_sixty_four_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, evidence = _indexed_files(tmp_path)
    monkeypatch.setattr(
        parallel_retrieval,
        "enriched_evidence_report",
        lambda query, **kwargs: _report(query),
    )

    for index in range(40):
        parallel_retrieval.run_parallel_retrieval(
            f"Question {index}?", sources=sources, evidence=evidence
        )

    assert retrieval_cache_size() == 64
