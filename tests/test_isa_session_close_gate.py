from __future__ import annotations

import pytest

from knowledge_engine_ai.copilot.intent import (
    CriterionResult,
    CriterionStatus,
    IdealStateCriterion,
    ResearchISA,
)
from knowledge_engine_ai.orchestrator.close_gate import attempt_session_close
from knowledge_engine_ai.sessions.models import ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import (
    DuplicateISAError,
    SessionRepository,
    UnknownISAError,
    new_connection,
)


def _session() -> ResearchSession:
    return ResearchSession(
        schema_version=1,
        session_id="session-isa-1",
        created_at="2026-08-11T02:00:00Z",
        updated_at="2026-08-11T02:00:00Z",
        user_question_original="Does the evidence support the claim?",
        status=SessionStatus.RUNNING,
    )


def _isa() -> ResearchISA:
    return ResearchISA(
        schema_version=1,
        run_id="run-isa-1",
        question="Does the evidence support the claim?",
        ideal_state="Produce a provenance-complete assessment with explicit uncertainty.",
        criteria=(
            IdealStateCriterion(
                criterion_id="ISC-01",
                claim="Every material scientific assertion has evidence links.",
                probe="citation_integrity_check",
            ),
            IdealStateCriterion(
                criterion_id="ISC-02",
                claim="Contradictory evidence was reviewed.",
                probe="contradiction_review_complete",
            ),
            IdealStateCriterion(
                criterion_id="ISC-03",
                claim="Optional teaching context was generated.",
                probe="teaching_context_check",
                required=False,
            ),
        ),
        known=("A primary retrieval run completed.",),
        unknown=("Whether all contradictory evidence has been reviewed.",),
        constraints=("Never fabricate citations.",),
    )


def _repository() -> SessionRepository:
    return SessionRepository(new_connection(":memory:"))


def test_attached_isa_round_trips_and_is_write_once() -> None:
    repository = _repository()
    repository.create_session(_session())
    isa = _isa()

    repository.attach_research_isa("session-isa-1", isa)

    assert repository.get_research_isa("session-isa-1") == isa
    with pytest.raises(DuplicateISAError):
        repository.attach_research_isa("session-isa-1", isa)


def test_criterion_results_are_append_only_and_latest_observation_wins() -> None:
    repository = _repository()
    repository.create_session(_session())
    repository.attach_research_isa("session-isa-1", _isa())

    repository.record_criterion_result(
        "session-isa-1",
        CriterionResult("ISC-01", CriterionStatus.FAILED, "One orphan citation remained."),
        recorded_at="2026-08-11T02:01:00Z",
    )
    repository.record_criterion_result(
        "session-isa-1",
        CriterionResult("ISC-01", CriterionStatus.PASSED, "orphan_citation_count == 0"),
        recorded_at="2026-08-11T02:02:00Z",
    )

    assert repository.latest_criterion_results("session-isa-1") == (
        CriterionResult("ISC-01", CriterionStatus.PASSED, "orphan_citation_count == 0"),
    )


def test_unknown_criterion_result_is_rejected() -> None:
    repository = _repository()
    repository.create_session(_session())
    repository.attach_research_isa("session-isa-1", _isa())

    with pytest.raises(ValueError, match="Unknown criterion_id"):
        repository.record_criterion_result(
            "session-isa-1",
            CriterionResult("ISC-99", CriterionStatus.PASSED, "not part of the ISA"),
            recorded_at="2026-08-11T02:01:00Z",
        )


def test_close_gate_blocks_when_a_required_probe_is_missing() -> None:
    repository = _repository()
    repository.create_session(_session())
    repository.attach_research_isa("session-isa-1", _isa())
    repository.record_criterion_result(
        "session-isa-1",
        CriterionResult("ISC-01", CriterionStatus.PASSED, "all citations resolve"),
        recorded_at="2026-08-11T02:01:00Z",
    )

    result = attempt_session_close(
        repository,
        session_id="session-isa-1",
        timestamp="2026-08-11T02:03:00Z",
    )

    assert result.status is SessionStatus.BLOCKED
    assert result.validation.complete is False
    assert result.validation.unresolved_required_criteria == ("ISC-02",)
    session = repository.get_session("session-isa-1")
    assert session is not None
    assert session.status is SessionStatus.BLOCKED
    assert repository.list_events("session-isa-1")[-1].validation_status == "blocked"


def test_close_gate_completes_only_after_all_required_probes_pass() -> None:
    repository = _repository()
    repository.create_session(_session())
    repository.attach_research_isa("session-isa-1", _isa())
    repository.record_criterion_result(
        "session-isa-1",
        CriterionResult("ISC-01", CriterionStatus.PASSED, "all citations resolve"),
        recorded_at="2026-08-11T02:01:00Z",
    )
    repository.record_criterion_result(
        "session-isa-1",
        CriterionResult("ISC-02", CriterionStatus.PASSED, "skeptic pass completed"),
        recorded_at="2026-08-11T02:02:00Z",
    )

    result = attempt_session_close(
        repository,
        session_id="session-isa-1",
        timestamp="2026-08-11T02:03:00Z",
    )

    assert result.status is SessionStatus.COMPLETED
    assert result.validation.complete is True
    assert result.validation.unresolved_required_criteria == ()
    session = repository.get_session("session-isa-1")
    assert session is not None
    assert session.status is SessionStatus.COMPLETED
    assert repository.list_events("session-isa-1")[-1].validation_status == "passed"


def test_close_gate_fails_closed_when_session_has_no_isa() -> None:
    repository = _repository()
    repository.create_session(_session())

    with pytest.raises(UnknownISAError):
        attempt_session_close(repository, session_id="session-isa-1")
