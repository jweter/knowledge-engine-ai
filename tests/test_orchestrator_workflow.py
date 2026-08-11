from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.orchestrator.workflow import run_fixed_evidence_workflow
from knowledge_engine_ai.sessions.models import ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection

_VALID_PAYLOAD = {
    "schema_version": 1,
    "question": "q",
    "sources_path": "sources.csv",
    "evidence_path": "evidence.jsonl",
    "evidence_summary": {
        "total": 1,
        "draft": 0,
        "reviewed": 1,
        "needs_revision": 0,
        "rejected": 0,
        "unspecified": 0,
        "readiness_note": "ready.",
    },
    "papers": [
        {
            "rank": 1,
            "paper_id": 1,
            "title": "T",
            "authors": "A",
            "year": "2026",
            "journal": "J",
            "doi": "10.1/x",
            "source_url": "https://example.org",
            "license_type": "CC BY",
            "metadata_source": "sources.csv",
            "retrieval_score": -1.0,
            "retrieval_snippet": "s",
            "why_matched": "m",
            "citation": "c",
            "evidence_records": [{"evidence_record_id": "ev-1"}],
        }
    ],
    "disclaimer": "This report is retrieval plus recorded evidence only.",
}

_VALID_INTELLIGENCE_PAYLOAD = {
    "schema_version": 1,
    "evidence_record_id": "ev-1",
    "claim_id": 1,
    "evidence_quality": {
        "score": 94,
        "study_design_tier": "randomized_controlled_trial",
        "manually_reviewed": True,
        "extraction_tier": "manual",
    },
    "evidence_consensus": {
        "relationship_edge_count": 2,
        "supports_count": 2,
        "contradicts_count": 0,
        "agreement_total": 2,
        "score": 100,
        "reliability": "moderate",
    },
    "claim_confidence": {"score": 89, "reliability": "moderate"},
    "evidence_coverage": {"records_in_relationship": 7, "total_records": 155, "percentage": 5},
    "synthesis": ["Evidence Quality: 94/100."],
    "scope_note": "Every number above is computed deterministically.",
}


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def repository() -> SessionRepository:
    connection = new_connection(":memory:")
    repo = SessionRepository(connection)
    repo.create_session(
        ResearchSession(
            schema_version=1,
            session_id="sess-1",
            created_at="2026-08-10T00:00:00Z",
            updated_at="2026-08-10T00:00:00Z",
            user_question_original="does semaglutide reduce body weight",
            status=SessionStatus.RUNNING,
        )
    )
    return repo


def _fake_run_success(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
    if command[1] == "evidence-report":
        return _FakeCompletedProcess(0, json.dumps(_VALID_PAYLOAD))
    if command[1] == "evidence-intelligence":
        return _FakeCompletedProcess(0, json.dumps(_VALID_INTELLIGENCE_PAYLOAD))
    if command[1] == "evidence-map-report":
        return _FakeCompletedProcess(0, "# Evidence Map Report\n\n...")
    if command[1] == "statistical-verify":
        return _FakeCompletedProcess(0, "# Statistical Verification\n\n...")
    raise AssertionError(f"Unexpected command: {command}")


def test_runs_retrieval_step_only_when_no_optional_inputs_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: SessionRepository
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run_success)

    result = run_fixed_evidence_workflow(
        session_id="sess-1",
        question="does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
    )

    assert [step.workflow_node for step in result.steps] == [
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
    ]
    assert result.steps[0].succeeded
    assert result.steps[1].succeeded
    assert result.evidence_report is not None
    assert result.evidence_report.papers[0].paper_id == 1
    assert result.parallel_retrieval is not None
    assert result.parallel_retrieval.primary.error is None
    assert result.parallel_retrieval.contradiction.error is None

    events = repository.list_events("sess-1")
    assert len(events) == 2
    assert events[0].workflow_node == "retrieval_and_evidence_intelligence"
    assert events[0].validation_status == "succeeded"
    assert events[0].tool_name == "ke evidence-report"
    assert events[0].output_hash is not None
    assert events[0].executor_type == "deterministic_tool"
    assert events[1].workflow_node == "contradiction_oriented_retrieval"
    assert events[1].validation_status == "succeeded"
    assert events[1].tool_name == "ke evidence-report (contradiction-oriented)"
    assert events[1].output_hash is not None

    # AI-O9: both retrieval events carry the same combined-call duration
    # and each carries its own branch's retrieved evidence-record IDs.
    assert events[0].duration_ms is not None and events[0].duration_ms >= 0
    assert events[0].duration_ms == events[1].duration_ms
    assert events[0].source_ids == ("ev-1",)
    assert events[1].source_ids == ("ev-1",)


def test_runs_all_fixed_steps_in_order_when_optional_inputs_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: SessionRepository
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run_success)

    result = run_fixed_evidence_workflow(
        session_id="sess-1",
        question="does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        evidence_map=tmp_path / "map.json",
        relationships=tmp_path / "rel.jsonl",
        statistical_inputs=tmp_path / "stats.jsonl",
    )

    assert [step.workflow_node for step in result.steps] == [
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
        "evidence_map",
        "statistical_verification",
    ]
    assert all(step.succeeded for step in result.steps)

    events = repository.list_events("sess-1")
    assert [event.workflow_node for event in events] == [
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
        "evidence_map",
        "statistical_verification",
    ]
    assert [event.tool_name for event in events] == [
        "ke evidence-report",
        "ke evidence-report (contradiction-oriented)",
        "ke evidence-map-report",
        "ke statistical-verify",
    ]


def test_skips_evidence_map_step_without_relationships_even_if_map_path_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: SessionRepository
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run_success)

    result = run_fixed_evidence_workflow(
        session_id="sess-1",
        question="q",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        evidence_map=tmp_path / "map.json",
    )

    assert [step.workflow_node for step in result.steps] == [
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
    ]


def test_a_failed_step_is_still_recorded_and_does_not_stop_later_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: SessionRepository
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        if command[1] == "evidence-report":
            return _FakeCompletedProcess(1, "", "No relevant papers found in the indexed corpus.")
        return _fake_run_success(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_fixed_evidence_workflow(
        session_id="sess-1",
        question="q",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        evidence_map=tmp_path / "map.json",
        relationships=tmp_path / "rel.jsonl",
    )

    assert result.evidence_report is None
    assert [step.workflow_node for step in result.steps] == [
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
        "evidence_map",
    ]
    assert result.steps[0].succeeded is False
    assert "No relevant papers found" in (result.steps[0].error or "")
    assert result.steps[1].succeeded is False
    assert "No relevant papers found" in (result.steps[1].error or "")
    assert result.steps[2].succeeded is True

    events = repository.list_events("sess-1")
    assert events[0].validation_status == "failed"
    assert events[0].notes is not None and "No relevant papers found" in events[0].notes
    assert events[0].output_hash is None
    assert events[1].validation_status == "failed"
    assert events[2].validation_status == "succeeded"


def test_raises_unknown_session_error_when_session_was_never_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine_ai.sessions.repository import UnknownSessionError

    monkeypatch.setattr(subprocess, "run", _fake_run_success)
    connection = new_connection(":memory:")
    repo = SessionRepository(connection)

    with pytest.raises(UnknownSessionError):
        run_fixed_evidence_workflow(
            session_id="never-created",
            question="q",
            session_repository=repo,
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
        )


def test_retrieval_output_hash_is_deterministic_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: SessionRepository
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run_success)

    result_one = run_fixed_evidence_workflow(
        session_id="sess-1",
        question="q",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
    )

    connection_two = new_connection(":memory:")
    repository_two = SessionRepository(connection_two)
    repository_two.create_session(
        ResearchSession(
            schema_version=1,
            session_id="sess-2",
            created_at="2026-08-10T00:00:00Z",
            updated_at="2026-08-10T00:00:00Z",
            user_question_original="q",
            status=SessionStatus.RUNNING,
        )
    )
    result_two = run_fixed_evidence_workflow(
        session_id="sess-2",
        question="q",
        session_repository=repository_two,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
    )

    hash_one = repository.list_events("sess-1")[0].output_hash
    hash_two = repository_two.list_events("sess-2")[0].output_hash
    assert hash_one == hash_two
    assert result_one.steps[0].output == result_two.steps[0].output


def test_binary_statistical_inputs_is_forwarded_to_ke_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository: SessionRepository
) -> None:
    captured: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured.append(command)
        return _fake_run_success(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_fixed_evidence_workflow(
        session_id="sess-1",
        question="q",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        statistical_inputs=tmp_path / "stats.jsonl",
        binary_statistical_inputs=tmp_path / "binary.jsonl",
    )

    stats_command = next(cmd for cmd in captured if cmd[1] == "statistical-verify")
    assert "--binary-inputs" in stats_command
    assert str(tmp_path / "binary.jsonl") in stats_command
