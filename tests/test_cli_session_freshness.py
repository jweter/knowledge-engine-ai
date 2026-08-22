from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

import knowledge_engine_ai.cli as cli
from knowledge_engine_ai.cli import app
from knowledge_engine_ai.ke_client import (
    FederatedCandidateObservation,
    FederatedCandidateRecord,
    FederatedCoverageReportResult,
    FederatedDiscoverHistoryResult,
    KeCommandError,
    SearchCoverageReport,
)
from knowledge_engine_ai.sessions.models import ResearchEvent, ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection


def _unwrapped(output: str) -> str:
    """Collapse Rich's line-wrapping so substring assertions survive it."""

    return " ".join(output.split())


def _coverage(
    search_run_id: str = "run-1",
    created_at: str = "2026-08-21T00:00:00Z",
    completeness: str = "complete",
) -> SearchCoverageReport:
    return SearchCoverageReport(
        search_run_id=search_run_id,
        created_at=created_at,
        query_text="does semaglutide reduce body weight",
        year_from=None,
        year_to=None,
        limit_per_provider=20,
        completeness=completeness,
        candidate_count=0,
        providers_requested=("pubmed",),
        providers_attempted=("pubmed",),
        providers_completed=("pubmed",),
        providers_failed=(),
    )


def _history(*runs: SearchCoverageReport) -> FederatedDiscoverHistoryResult:
    return FederatedDiscoverHistoryResult(
        research_question_id="q-1", run_count=len(runs), runs=runs
    )


def _observation(
    provider: str = "crossref", *, retracted: bool | None = None, corrected: bool | None = None
) -> FederatedCandidateObservation:
    return FederatedCandidateObservation(
        provider=provider,
        provider_id="p-1",
        title="A trial of semaglutide",
        authors=(),
        publication_year=2024,
        venue=None,
        abstract=None,
        doi="10.1000/example",
        pmid=None,
        pmcid=None,
        arxiv_id=None,
        openalex_id=None,
        semantic_scholar_id=None,
        landing_url=None,
        full_text_url=None,
        xml_url=None,
        license=None,
        metadata_source=None,
        pmcid_source=None,
        open_access_source=None,
        citation_count=None,
        open_access=None,
        retracted=retracted,
        preprint=None,
        preprint_version=None,
        related_journal_doi=None,
        related_journal_reference=None,
        retrieved_at=None,
        corrected=corrected,
        expression_of_concern=None,
        withdrawn=None,
    )


def _candidate(
    canonical_id: str,
    *,
    doi: str | None = "10.1000/example",
    observations: tuple[FederatedCandidateObservation, ...] = (),
) -> FederatedCandidateRecord:
    return FederatedCandidateRecord(
        canonical_id=canonical_id,
        title="A trial of semaglutide",
        observations=observations,
        doi=doi,
        publication_year=2024,
    )


def _snapshot(
    *candidates: FederatedCandidateRecord, search_run_id: str = "run-1"
) -> FederatedCoverageReportResult:
    return FederatedCoverageReportResult(
        search_run_id=search_run_id,
        coverage=_coverage(search_run_id=search_run_id),
        candidates=candidates,
    )


def _seed_session(
    db_path: str,
    *,
    session_id: str = "session-1",
    research_question_id: str | None = "q-1",
    narrative: str | None = "Semaglutide reduces body weight [ev-1].",
    source_ids: tuple[str, ...] = ("ev-1",),
    source_dois: tuple[str, ...] = ("10.1000/example",),
) -> None:
    repository = SessionRepository(new_connection(db_path))
    repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id=session_id,
            created_at="2026-08-09T00:00:00Z",
            updated_at="2026-08-09T00:00:00Z",
            user_question_original="Does semaglutide produce long-term weight loss?",
            status=SessionStatus.COMPLETED,
            research_question_id=research_question_id,
        )
    )
    repository.append_event(
        ResearchEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp="2026-08-09T00:00:01Z",
            workflow_node="retrieval",
            executor_type="tool",
            source_ids=source_ids,
            source_dois=source_dois,
        )
    )
    if narrative is not None:
        repository.append_event(
            ResearchEvent(
                event_id=str(uuid.uuid4()),
                session_id=session_id,
                timestamp="2026-08-09T00:00:02Z",
                workflow_node="synthesis",
                executor_type="local_llm",
                validation_status="succeeded",
                notes=narrative,
            )
        )


def _invoke(args: list[str]) -> Result:
    return CliRunner().invoke(app, ["session-freshness", *args])


def test_session_freshness_unknown_session_errors(tmp_path: Path) -> None:
    db_path = str(tmp_path / "sessions.db")
    SessionRepository(new_connection(db_path))  # create empty schema

    result = _invoke(["missing-session", "--ledger-root", "/tmp/ledger", "--session-db", db_path])

    assert result.exit_code == 1
    assert "No session with session_id" in result.output


def test_session_freshness_reports_no_research_question_id(tmp_path: Path) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path, research_question_id=None)

    result = _invoke(["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path])

    assert result.exit_code == 0, result.output
    assert "has no research_question_id" in result.output


def test_session_freshness_no_diff_with_a_single_recorded_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(_coverage())
    )

    result = _invoke(["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path])

    assert result.exit_code == 0, result.output
    body = _unwrapped(result.output)
    assert "no rerun needed" in body
    assert "Fewer than two recorded runs" in body
    assert "Answer freshness: version 1, status=completed, releaseable=yes" in body


def test_session_freshness_reports_invalidating_flip_without_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)

    older = _coverage(search_run_id="run-older", created_at="2026-08-01T00:00:00Z")
    newer = _coverage(search_run_id="run-newer", created_at="2026-08-21T00:00:00Z")
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(older, newer)
    )

    previous_snapshot = _snapshot(
        _candidate("c-1", observations=(_observation(),)), search_run_id="run-older"
    )
    current_snapshot = _snapshot(
        _candidate("c-1", observations=(_observation(retracted=True),)),
        search_run_id="run-newer",
    )

    def fake_coverage_report(search_run_id: str, **kwargs: object) -> FederatedCoverageReportResult:
        return previous_snapshot if search_run_id == "run-older" else current_snapshot

    monkeypatch.setattr(cli, "federated_coverage_report", fake_coverage_report)

    result = _invoke(["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path])

    assert result.exit_code == 0, result.output
    body = _unwrapped(result.output)
    assert "retracted (invalidates)" in body
    assert "Run with --apply to persist" in body

    # Nothing was written without --apply.
    repository = SessionRepository(new_connection(db_path))
    fetched = repository.get_session("session-1")
    assert fetched is not None
    assert fetched.narrative_invalidated_at is None


def test_session_freshness_apply_persists_invalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)

    older = _coverage(search_run_id="run-older", created_at="2026-08-01T00:00:00Z")
    newer = _coverage(search_run_id="run-newer", created_at="2026-08-21T00:00:00Z")
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(older, newer)
    )

    previous_snapshot = _snapshot(
        _candidate("c-1", observations=(_observation(),)), search_run_id="run-older"
    )
    current_snapshot = _snapshot(
        _candidate("c-1", observations=(_observation(retracted=True),)),
        search_run_id="run-newer",
    )

    def fake_coverage_report(search_run_id: str, **kwargs: object) -> FederatedCoverageReportResult:
        return previous_snapshot if search_run_id == "run-older" else current_snapshot

    monkeypatch.setattr(cli, "federated_coverage_report", fake_coverage_report)

    result = _invoke(
        ["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path, "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "narrative_invalidated_at recorded" in result.output
    # The Answer freshness section reflects the *post*-apply state, not the
    # value read before `apply_narrative_touching_flips` ran.
    body = _unwrapped(result.output)
    assert "releaseable=no" in body
    assert "narrative_invalidated_at:" in body

    repository = SessionRepository(new_connection(db_path))
    fetched = repository.get_session("session-1")
    assert fetched is not None
    assert fetched.narrative_invalidated_at is not None

    # A second run is idempotent -- no error, no duplicate event.
    result_again = _invoke(
        ["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path, "--apply"]
    )
    assert result_again.exit_code == 0, result_again.output
    assert "already marked invalidated" in result_again.output
    assert "releaseable=no" in _unwrapped(result_again.output)


def test_session_freshness_qualifying_flip_is_never_persisted_even_with_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)

    older = _coverage(search_run_id="run-older", created_at="2026-08-01T00:00:00Z")
    newer = _coverage(search_run_id="run-newer", created_at="2026-08-21T00:00:00Z")
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(older, newer)
    )

    previous_snapshot = _snapshot(
        _candidate("c-1", observations=(_observation(),)), search_run_id="run-older"
    )
    current_snapshot = _snapshot(
        _candidate("c-1", observations=(_observation(corrected=True),)),
        search_run_id="run-newer",
    )

    def fake_coverage_report(search_run_id: str, **kwargs: object) -> FederatedCoverageReportResult:
        return previous_snapshot if search_run_id == "run-older" else current_snapshot

    monkeypatch.setattr(cli, "federated_coverage_report", fake_coverage_report)

    result = _invoke(
        ["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path, "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "corrected (qualifies)" in _unwrapped(result.output)
    assert "qualifying flip(s) found -- not persisted" in _unwrapped(result.output)

    repository = SessionRepository(new_connection(db_path))
    fetched = repository.get_session("session-1")
    assert fetched is not None
    assert fetched.narrative_invalidated_at is None


def test_session_freshness_flip_not_cited_is_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The flagged candidate's DOI does not match anything the session cited.
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)

    older = _coverage(search_run_id="run-older", created_at="2026-08-01T00:00:00Z")
    newer = _coverage(search_run_id="run-newer", created_at="2026-08-21T00:00:00Z")
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(older, newer)
    )

    previous_snapshot = _snapshot(search_run_id="run-older")
    current_snapshot = _snapshot(
        _candidate("c-1", doi="10.1000/never-cited", observations=(_observation(retracted=True),)),
        search_run_id="run-newer",
    )

    def fake_coverage_report(search_run_id: str, **kwargs: object) -> FederatedCoverageReportResult:
        return previous_snapshot if search_run_id == "run-older" else current_snapshot

    monkeypatch.setattr(cli, "federated_coverage_report", fake_coverage_report)

    result = _invoke(["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path])

    assert result.exit_code == 0, result.output
    assert "Flips touching this session's cited narrative: none" in _unwrapped(result.output)


def test_session_freshness_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(_coverage())
    )

    result = _invoke(
        ["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["session_id"] == "session-1"
    assert payload["research_question_id"] == "q-1"
    assert payload["checked"] is True
    assert payload["diff"] is None
    assert payload["applied"] is False
    assert payload["answer_freshness"] == {
        "status": "completed",
        "supersedes_session_id": None,
        "superseded_by_session_id": None,
        "narrative_invalidated_at": None,
        "releaseable": True,
        "pending_flip_count": 0,
    }


def test_session_freshness_answer_freshness_finds_superseded_by_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path, session_id="session-1", research_question_id="q-1")
    repository = SessionRepository(new_connection(db_path))
    repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id="session-2",
            created_at="2026-08-15T00:00:00Z",
            updated_at="2026-08-15T00:00:00Z",
            user_question_original="Does semaglutide produce long-term weight loss?",
            status=SessionStatus.COMPLETED,
            research_question_id="q-1",
            answer_version=2,
            supersedes_session_id="session-1",
        )
    )
    monkeypatch.setattr(
        cli, "federated_discover_history", lambda rqid, **kwargs: _history(_coverage())
    )

    result = _invoke(
        ["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["answer_freshness"]["superseded_by_session_id"] == "session-2"


def test_session_freshness_reports_ke_command_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)

    def fail(rqid: str, **kwargs: object) -> FederatedDiscoverHistoryResult:
        raise KeCommandError("`ke federated-discover-history` exited 1: boom")

    monkeypatch.setattr(cli, "federated_discover_history", fail)

    result = _invoke(["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path])

    assert result.exit_code == 1
    assert "boom" in result.output


def test_session_freshness_rejects_an_unknown_format(tmp_path: Path) -> None:
    db_path = str(tmp_path / "sessions.db")
    _seed_session(db_path)

    result = _invoke(
        ["session-1", "--ledger-root", "/tmp/ledger", "--session-db", db_path, "--format", "xml"]
    )

    assert result.exit_code != 0
