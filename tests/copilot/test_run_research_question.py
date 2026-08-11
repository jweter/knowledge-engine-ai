from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.copilot.run_research_question import run_research_question
from knowledge_engine_ai.llm import LocalLLMError
from knowledge_engine_ai.sessions.models import SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection


def _payload(
    *, evidence_records: list[dict[str, object]] | None = None, papers: bool = True
) -> dict[str, object]:
    return {
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
        "papers": (
            [
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
                    "evidence_records": (evidence_records if evidence_records is not None else []),
                }
            ]
            if papers
            else []
        ),
        "disclaimer": "This report is retrieval plus recorded evidence only.",
    }


_GROUNDED_RECORD: dict[str, object] = {
    "evidence_record_id": "ev-1",
    "claim_text": "Semaglutide reduced body weight.",
    "evidence_direction": "supports",
}

_QUALIFYING_RECORD: dict[str, object] = {
    "evidence_record_id": "ev-2",
    "claim_text": "Effect size varies by baseline BMI.",
    "evidence_direction": "qualifies",
}


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeLLM:
    def __init__(
        self, response: str = "Semaglutide reduced body weight [ev-1].", *, error: bool = False
    ) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, max_tokens: int = 400) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise LocalLLMError("Could not reach Ollama.")
        return self.response


def _repository() -> SessionRepository:
    return SessionRepository(new_connection(":memory:"))


def _fake_run(payload: dict[str, object]) -> object:
    def _run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        if command[1] == "evidence-report":
            return _FakeCompletedProcess(0, json.dumps(payload))
        if command[1] == "evidence-intelligence":
            # No graph claim yet for any record in these fixtures -- the
            # expected, common state `evidence_intelligence` documents for
            # a record `evidence-report` just matched but `ke graph-build`
            # has not processed yet.
            return _FakeCompletedProcess(1, "", "No graph claim found for this record.")
        raise AssertionError(f"Unexpected command: {command}")

    return _run


def test_full_run_produces_a_clean_verified_narrative_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    llm = _FakeLLM()

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
    )

    assert result.narrative == "Semaglutide reduced body weight [ev-1]."
    assert result.synthesis_error is None
    assert result.verification is not None
    assert result.verification.is_clean
    assert result.session_report is not None
    assert result.session_report.is_fully_sourced
    assert result.close_result.status is SessionStatus.COMPLETED
    assert result.close_result.validation.complete is True

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.status is SessionStatus.COMPLETED
    assert session.user_question_original == "does semaglutide reduce body weight"

    assert result.trace.session_id == result.session_id
    assert "synthesis" in [event.workflow_node for event in result.trace.events]
    assert result.trace.all_succeeded


def test_no_retrievable_evidence_passes_vacuously_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(papers=False)))
    repository = _repository()
    llm = _FakeLLM()

    result = run_research_question(
        "a question with no matching evidence",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
    )

    assert result.narrative is None
    assert result.synthesis_error is None
    assert result.verification is None
    assert result.session_report is None
    assert llm.prompts == []  # never called -- nothing to narrate
    assert result.close_result.status is SessionStatus.COMPLETED


def test_llm_failure_is_recorded_but_still_completes_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    llm = _FakeLLM(error=True)

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
    )

    assert result.narrative is None
    assert result.synthesis_error == "Could not reach Ollama."
    assert result.verification is None
    # The ISA close gate is scoped to narrative correctness, not synthesis
    # availability -- a synthesis failure is durable/visible (below) but
    # does not block session close.
    assert result.close_result.status is SessionStatus.COMPLETED

    synthesis_events = [
        event
        for event in repository.list_events(result.session_id)
        if event.workflow_node == "synthesis"
    ]
    assert len(synthesis_events) == 1
    assert synthesis_events[0].validation_status == "failed"
    assert synthesis_events[0].notes == "Could not reach Ollama."


def test_hallucinated_citation_blocks_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    llm = _FakeLLM(response="A fabricated claim [ev-does-not-exist].")

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
    )

    assert result.verification is not None
    assert result.verification.hallucinated_citations == ("ev-does-not-exist",)
    assert result.close_result.status is SessionStatus.BLOCKED
    assert "citation_integrity" in result.close_result.validation.unresolved_required_criteria

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.status is SessionStatus.BLOCKED


def test_missed_qualifying_evidence_blocks_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(_payload(evidence_records=[_GROUNDED_RECORD, _QUALIFYING_RECORD])),
    )
    repository = _repository()
    # Narrative cites only ev-1, silently omitting the qualifying ev-2.
    llm = _FakeLLM(response="Semaglutide reduced body weight [ev-1].")

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
    )

    assert result.verification is not None
    assert result.verification.missed_qualifiers == ("ev-2",)
    assert result.close_result.status is SessionStatus.BLOCKED
    assert "contradiction_review" in result.close_result.validation.unresolved_required_criteria


def test_session_id_is_generated_and_events_are_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    assert result.session_id
    events = repository.list_events(result.session_id)
    workflow_nodes = [event.workflow_node for event in events]
    assert workflow_nodes == [
        "retrieval_and_evidence_intelligence",
        "contradiction_oriented_retrieval",
        "synthesis",
        "research_isa_close_gate",
    ]

    isa = repository.get_research_isa(result.session_id)
    assert isa is not None
    assert isa.question == "does semaglutide reduce body weight"
    assert {criterion.criterion_id for criterion in isa.criteria} == {
        "citation_integrity",
        "contradiction_review",
    }
