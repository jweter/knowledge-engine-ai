from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import knowledge_engine_ai.copilot.discovery_policy as discovery_policy
from knowledge_engine_ai.copilot.discovery_policy import FederatedDiscoveryPolicy
from knowledge_engine_ai.copilot.progress_report import ResearchProgressStage
from knowledge_engine_ai.copilot.run_research_question import run_research_question
from knowledge_engine_ai.ke_client import (
    CitationSnowballResult,
    FederatedDiscoveryResult,
    FederatedProviderStatus,
)
from knowledge_engine_ai.llm import LocalLLMError
from knowledge_engine_ai.sessions.models import SessionStatus
from knowledge_engine_ai.sessions.repository import (
    DuplicateSessionError,
    SessionRepository,
    new_connection,
)


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
        self.timeouts: list[float | None] = []

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        self.prompts.append(prompt)
        self.timeouts.append(timeout_seconds)
        if self.error:
            raise LocalLLMError("Could not reach Ollama.")
        return self.response


def _repository() -> SessionRepository:
    return SessionRepository(new_connection(":memory:"))


def _fake_run(
    payload: dict[str, object],
) -> Callable[..., _FakeCompletedProcess]:
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
    assert result.narrative_releaseable is True

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.status is SessionStatus.COMPLETED
    assert session.user_question_original == "does semaglutide reduce body weight"

    assert result.trace.session_id == result.session_id
    assert "synthesis" in [event.workflow_node for event in result.trace.events]
    assert result.trace.all_succeeded


def test_caller_supplied_session_id_is_persisted_and_returned(
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
        session_id="web-session-123",
    )

    assert result.session_id == "web-session-123"
    session = repository.get_session("web-session-123")
    assert session is not None
    assert session.session_id == "web-session-123"


def test_omitted_session_id_still_generates_unique_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()

    first = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )
    second = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    assert first.session_id
    assert second.session_id
    assert first.session_id != second.session_id


def test_blank_caller_session_id_is_rejected_before_execution(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="session_id must be non-blank"):
        run_research_question(
            "does semaglutide reduce body weight",
            session_repository=_repository(),
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
            llm=_FakeLLM(),
            session_id="   ",
        )


def test_duplicate_caller_session_id_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()

    run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        session_id="web-session-duplicate",
    )
    with pytest.raises(DuplicateSessionError):
        run_research_question(
            "does semaglutide reduce body weight",
            session_repository=repository,
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
            llm=_FakeLLM(),
            session_id="web-session-duplicate",
        )


def test_full_run_shares_one_execution_budget_across_core_and_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess_timeouts: list[float | None] = []
    fake_run = _fake_run(_payload(evidence_records=[_GROUNDED_RECORD]))

    def capture_timeout(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        timeout = kwargs.get("timeout")
        subprocess_timeouts.append(timeout if isinstance(timeout, float) else None)
        return fake_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", capture_timeout)
    llm = _FakeLLM()

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=_repository(),
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
        timeout_seconds=10.0,
    )

    assert result.narrative is not None
    assert subprocess_timeouts
    assert all(timeout is not None and 0 < timeout <= 10.0 for timeout in subprocess_timeouts)
    assert len(llm.timeouts) == 1
    assert llm.timeouts[0] is not None
    assert 0 < llm.timeouts[0] <= 10.0


def test_min_synthesis_seconds_requires_timeout_seconds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires timeout_seconds"):
        run_research_question(
            "does semaglutide reduce body weight",
            session_repository=_repository(),
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
            llm=_FakeLLM(),
            min_synthesis_seconds=5.0,
        )


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_min_synthesis_seconds_must_be_positive(tmp_path: Path, value: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        run_research_question(
            "does semaglutide reduce body weight",
            session_repository=_repository(),
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
            llm=_FakeLLM(),
            timeout_seconds=10.0,
            min_synthesis_seconds=value,
        )


def test_min_synthesis_seconds_must_be_less_than_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="less than timeout_seconds"):
        run_research_question(
            "does semaglutide reduce body weight",
            session_repository=_repository(),
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
            llm=_FakeLLM(),
            timeout_seconds=10.0,
            min_synthesis_seconds=10.0,
        )


def test_min_synthesis_seconds_reserves_time_for_synthesis_over_upstream_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BT-4 (issue #87): a cold/slow upstream stage must not starve synthesis.

    Without ``min_synthesis_seconds``, retrieval and synthesis draw on the same
    shared deadline (see ``test_full_run_shares_one_execution_budget_across_core_and_ollama``
    above). With it, the upstream retrieval call is bounded by the *reserved*
    (shorter) budget while synthesis still sees the original, unreserved one.
    """

    subprocess_timeouts: list[float | None] = []
    fake_run = _fake_run(_payload(evidence_records=[_GROUNDED_RECORD]))

    def capture_timeout(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        timeout = kwargs.get("timeout")
        subprocess_timeouts.append(timeout if isinstance(timeout, float) else None)
        return fake_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", capture_timeout)
    llm = _FakeLLM()

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=_repository(),
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
        timeout_seconds=10.0,
        min_synthesis_seconds=8.0,
    )

    assert result.narrative is not None
    assert subprocess_timeouts
    # Retrieval ran against the reserved (~2s) upstream budget...
    assert all(timeout is not None and 0 < timeout <= 3.0 for timeout in subprocess_timeouts)
    # ...while synthesis still ran against the full, unreserved 10s budget.
    assert len(llm.timeouts) == 1
    assert llm.timeouts[0] is not None
    assert 5.0 < llm.timeouts[0] <= 10.0


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


def test_failed_retrieval_workflow_blocks_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_retrieval(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        del command, kwargs
        return _FakeCompletedProcess(1, "", "Core retrieval failed.")

    monkeypatch.setattr(subprocess, "run", fail_retrieval)
    repository = _repository()

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    assert result.narrative is None
    assert result.close_result.status is SessionStatus.BLOCKED
    assert "workflow_integrity" in result.close_result.validation.unresolved_required_criteria
    assert result.narrative_releaseable is False

    criterion_results = repository.latest_criterion_results(result.session_id)
    workflow_result = next(
        item for item in criterion_results if item.criterion_id == "workflow_integrity"
    )
    assert workflow_result.status.value == "failed"
    assert "retrieval_and_evidence_intelligence" in workflow_result.evidence
    assert "contradiction_oriented_retrieval" in workflow_result.evidence


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
    assert result.narrative_releaseable is False
    assert "citation_integrity" in result.close_result.validation.unresolved_required_criteria

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.status is SessionStatus.BLOCKED


def test_missed_qualifying_evidence_is_appended_before_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(_payload(evidence_records=[_GROUNDED_RECORD, _QUALIFYING_RECORD])),
    )
    repository = _repository()
    # The small model cites only ev-1. Synthesis must append ev-2 from the
    # retrieved evidence rather than weakening the contradiction-review gate.
    llm = _FakeLLM(response="Semaglutide reduced body weight [ev-1].")

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
    )

    assert result.narrative is not None
    assert "Semaglutide reduced body weight [ev-1]." in result.narrative
    assert "Evidence qualifications and limitations:" in result.narrative
    assert "[ev-2]" in result.narrative
    assert result.verification is not None
    assert result.verification.missed_qualifiers == ()
    assert result.verification.is_clean
    assert result.close_result.status is SessionStatus.COMPLETED
    assert result.narrative_releaseable is True


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
        "workflow_integrity",
        "citation_integrity",
        "contradiction_review",
    }
    assert result.discovery is None  # no discovery_policy supplied -- unchanged default path


# --- research_question_id threading (answer/session-versioning design) ------


def test_research_question_id_is_derived_deterministically_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()

    first = run_research_question(
        "Does semaglutide reduce body weight?",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )
    # Different casing/whitespace, same normalized question -- same thread.
    second = run_research_question(
        "  does semaglutide reduce body weight?  ",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )
    # A genuinely different question derives a different thread identity.
    third = run_research_question(
        "does metformin reduce hba1c",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    first_session = repository.get_session(first.session_id)
    second_session = repository.get_session(second.session_id)
    third_session = repository.get_session(third.session_id)
    assert first_session is not None
    assert second_session is not None
    assert third_session is not None

    assert first_session.research_question_id is not None
    assert first_session.research_question_id.startswith("rq-")
    assert first_session.research_question_id == second_session.research_question_id
    assert first_session.research_question_id != third_session.research_question_id


def test_research_question_id_uses_caller_supplied_value_verbatim(
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
        research_question_id="rq-caller-supplied",
    )

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.research_question_id == "rq-caller-supplied"


# --- answer_version/supersedes_session_id threading (answer/session-versioning) ---


def test_answer_version_and_supersedes_session_id_default_to_first_version(
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

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.answer_version == 1
    assert session.supersedes_session_id is None


def test_answer_version_and_supersedes_session_id_are_set_verbatim_when_supplied(
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
        research_question_id="rq-caller-supplied",
        answer_version=2,
        supersedes_session_id="session-prior",
    )

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.answer_version == 2
    assert session.supersedes_session_id == "session-prior"


# --- AI-FRD-3/AI-FRD-4 wiring (discovery_policy) ------------------------------


def _federated_discovery_stub(*args: object, **kwargs: object) -> FederatedDiscoveryResult:
    del args, kwargs
    return FederatedDiscoveryResult(
        search_run_id="run-xyz",
        query_text="does semaglutide reduce body weight",
        completeness="complete",
        provider_statuses=(),
        candidates=(),
        provider_disagreements=None,
        search_run_created_at=None,
    )


def _citation_snowball_stub(*args: object, **kwargs: object) -> CitationSnowballResult:
    del args, kwargs
    return CitationSnowballResult(
        snowball_run_id="snowball-abc",
        provider="semantic_scholar",
        seed_identifiers=("10.1/x",),
        directions=("references", "citations"),
        max_depth=1,
        limit_per_traversal=25,
        max_candidates=50,
        completeness="complete",
        truncated=False,
        candidates=(),
        edges=(),
    )


def test_discovery_policy_not_evaluated_when_no_policy_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not attempt any discovery/snowball call.")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _fail)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(papers=False)))
    repository = _repository()

    result = run_research_question(
        "a question with no matching evidence",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    assert result.discovery is None
    workflow_nodes = [event.workflow_node for event in repository.list_events(result.session_id)]
    assert "federated_discovery" not in workflow_nodes
    assert "citation_snowball" not in workflow_nodes


def test_discovery_policy_triggers_on_thin_coverage_and_is_recorded_before_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _federated_discovery_stub)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    llm = _FakeLLM()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=5
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=llm,
        discovery_policy=policy,
    )

    assert result.discovery is not None
    assert result.discovery.triggered is True
    assert result.discovery.federated_discovery is not None
    assert result.discovery.federated_discovery.search_run_id == "run-xyz"
    assert result.discovery.citation_snowball is not None
    assert result.discovery.citation_snowball.snowball_run_id == "snowball-abc"

    # The narrative still only cites the grounded corpus evidence record --
    # discovery/snowball candidates are never fed into synthesis.
    assert result.narrative == "Semaglutide reduced body weight [ev-1]."
    assert "[ev-1]" in llm.prompts[0]
    assert "run-xyz" not in llm.prompts[0]
    assert "snowball-abc" not in llm.prompts[0]

    workflow_nodes = [event.workflow_node for event in repository.list_events(result.session_id)]
    assert workflow_nodes.index("federated_discovery") < workflow_nodes.index("synthesis")
    assert workflow_nodes.index("citation_snowball") < workflow_nodes.index("synthesis")

    # Discovery events never contribute to "what evidence supported the output."
    discovery_events = [
        event
        for event in repository.list_events(result.session_id)
        if event.workflow_node in ("federated_discovery", "citation_snowball")
    ]
    for event in discovery_events:
        assert event.source_ids == ()
    assert result.trace.evidence_record_ids == ("ev-1",)


def test_discovery_step_receives_the_session_research_question_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _capturing_execute_discovery_plan(
        plan: object, **kwargs: object
    ) -> FederatedDiscoveryResult:
        captured.update(kwargs)
        return _federated_discovery_stub(plan, **kwargs)

    monkeypatch.setattr(
        discovery_policy, "execute_discovery_plan", _capturing_execute_discovery_plan
    )
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=5
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
        research_question_id="rq-caller-supplied",
    )

    session = repository.get_session(result.session_id)
    assert session is not None
    assert session.research_question_id == "rq-caller-supplied"
    assert captured["research_question_id"] == "rq-caller-supplied"


def test_discovery_policy_does_not_trigger_when_coverage_already_sufficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not attempt any discovery/snowball call.")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _fail)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=1
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    assert result.discovery is not None
    assert result.discovery.triggered is False
    assert result.narrative == "Semaglutide reduced body weight [ev-1]."
    assert result.close_result.status is SessionStatus.COMPLETED


# --- AI-FRD-2 wiring (coverage-aware Research ISA) ----------------------------


def test_discovery_coverage_criterion_absent_when_no_discovery_policy_supplied(
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

    isa = repository.get_research_isa(result.session_id)
    assert isa is not None
    assert {criterion.criterion_id for criterion in isa.criteria} == {
        "workflow_integrity",
        "citation_integrity",
        "contradiction_review",
    }
    criterion_ids = {
        item.criterion_id for item in repository.latest_criterion_results(result.session_id)
    }
    assert "discovery_coverage" not in criterion_ids


def test_discovery_coverage_criterion_not_applicable_when_not_triggered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not attempt any discovery/snowball call.")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _fail)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=1
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    isa = repository.get_research_isa(result.session_id)
    assert isa is not None
    discovery_criterion = next(c for c in isa.criteria if c.criterion_id == "discovery_coverage")
    assert discovery_criterion.required is False

    criterion_result = next(
        item
        for item in repository.latest_criterion_results(result.session_id)
        if item.criterion_id == "discovery_coverage"
    )
    assert criterion_result.status.value == "not_applicable"
    assert result.close_result.status is SessionStatus.COMPLETED


def test_discovery_coverage_criterion_passes_when_all_providers_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _federated_discovery_stub)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=5
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    criterion_result = next(
        item
        for item in repository.latest_criterion_results(result.session_id)
        if item.criterion_id == "discovery_coverage"
    )
    assert criterion_result.status.value == "passed"
    assert "run-xyz" in criterion_result.evidence
    assert result.close_result.status is SessionStatus.COMPLETED


def _provider_status(
    provider: str, *, outcome: str, attempted: bool, result_count: int, reason: str | None = None
) -> FederatedProviderStatus:
    return FederatedProviderStatus(
        provider=provider,
        outcome=outcome,
        attempted=attempted,
        result_count=result_count,
        reason=reason,
    )


def _degraded_federated_discovery_stub(*args: object, **kwargs: object) -> FederatedDiscoveryResult:
    del args, kwargs
    return FederatedDiscoveryResult(
        search_run_id="run-degraded",
        query_text="does semaglutide reduce body weight",
        completeness="partial",
        provider_statuses=(
            _provider_status("pubmed", outcome="success", attempted=True, result_count=3),
            _provider_status(
                "semantic_scholar",
                outcome="rate_limited",
                attempted=True,
                result_count=0,
                reason="429 Too Many Requests",
            ),
        ),
        candidates=(),
        provider_disagreements=None,
        search_run_created_at=None,
    )


def test_discovery_coverage_criterion_fails_on_failed_provider_without_blocking_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        discovery_policy, "execute_discovery_plan", _degraded_federated_discovery_stub
    )
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=5
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    criterion_result = next(
        item
        for item in repository.latest_criterion_results(result.session_id)
        if item.criterion_id == "discovery_coverage"
    )
    assert criterion_result.status.value == "failed"
    assert "semantic_scholar=rate_limited" in criterion_result.evidence
    assert "429 Too Many Requests" in criterion_result.evidence

    # Optional criterion: a degraded federated-discovery broadening is
    # visible and explicit, but does not by itself block session close --
    # synthesis may still proceed in degraded mode.
    assert result.close_result.status is SessionStatus.COMPLETED
    assert "discovery_coverage" not in result.close_result.validation.unresolved_required_criteria


def test_discovery_coverage_criterion_not_applicable_when_federated_discovery_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Federated discovery is disabled by policy; should not be attempted.")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _fail)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger",
        min_evidence_record_coverage=5,
        enable_federated_discovery=False,
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    criterion_result = next(
        item
        for item in repository.latest_criterion_results(result.session_id)
        if item.criterion_id == "discovery_coverage"
    )
    # The coverage gap was real (triggered=True) but federated discovery was
    # never attempted because policy disabled it -- this must not be
    # reported as a provider FAILURE, only as not applicable.
    assert criterion_result.status.value == "not_applicable"
    assert result.close_result.status is SessionStatus.COMPLETED


# --- BT-6 progressive report contract wiring (issue #90) ---------------------


def test_full_run_populates_a_final_answer_progress_report(
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

    assert result.progress_report is not None
    assert result.progress_report.session_id == result.session_id
    assert result.progress_report.progress_stage is ResearchProgressStage.FINAL_ANSWER
    assert result.progress_report.final is True
    assert result.progress_report.answer_available is True
    assert result.progress_report.indexed_evidence_record_ids == ("ev-1",)
    assert result.progress_report.newly_acquired_evidence_record_ids == ()
    assert [claim.evidence_record_id for claim in result.progress_report.citations] == ["ev-1"]


def test_no_retrievable_evidence_progress_report_is_final_insufficient_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(papers=False)))
    repository = _repository()

    result = run_research_question(
        "a question with no matching evidence",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    assert result.progress_report is not None
    assert result.progress_report.progress_stage is ResearchProgressStage.INSUFFICIENT_EVIDENCE
    assert result.progress_report.final is True
    assert result.progress_report.answer_available is False


# --- BT-2 conversion-funnel report wiring (issue #88) -------------------------


def test_full_run_populates_a_conversion_funnel_report(
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

    assert result.conversion_funnel_report is not None
    assert result.conversion_funnel_report.session_id == result.session_id
    assert result.conversion_funnel_report.discovery_triggered is False
    assert result.conversion_funnel_report.indexed_evidence_record_count == 1
    assert result.conversion_funnel_report.acquisition_plan is None
    assert result.conversion_funnel_report.time_to_final_report_ms is not None


def test_no_retrievable_evidence_conversion_funnel_has_no_indexed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(papers=False)))
    repository = _repository()

    result = run_research_question(
        "a question with no matching evidence",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )

    assert result.conversion_funnel_report is not None
    assert result.conversion_funnel_report.indexed_evidence_record_count == 0
    assert result.conversion_funnel_report.time_to_first_grounded_information_ms is None


def test_discovery_triggered_conversion_funnel_reports_candidate_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _federated_discovery_stub)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=5
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    assert result.conversion_funnel_report is not None
    assert result.conversion_funnel_report.discovery_triggered is True
    # `_federated_discovery_stub` returns no candidates; the funnel must report
    # exactly what Core returned, not fabricate a nonzero count.
    assert result.conversion_funnel_report.federated_discovery_candidate_count == 0


def test_discovery_triggered_with_releaseable_indexed_answer_progress_report_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _federated_discovery_stub)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=5
    )

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    assert result.discovery is not None
    assert result.discovery.triggered is True
    assert result.grounded_completion is None
    assert result.progress_report is not None
    assert result.progress_report.progress_stage is ResearchProgressStage.PARTIAL_ANSWER
    assert result.progress_report.final is False
    assert result.progress_report.answer_available is True
    assert result.progress_report.wait_reason is None


def test_zero_evidence_with_discovery_triggered_is_research_required_not_insufficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BT-6 product invariant (issue #90), exercised through the real wiring: a
    zero-record initial indexed retrieval with discovery triggered but not carried
    through a grounded-completion attempt this call must resolve to
    `research_required`, never a final `insufficient_evidence`.
    """

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _federated_discovery_stub)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _citation_snowball_stub)
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(papers=False)))
    repository = _repository()
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=1
    )

    result = run_research_question(
        "a question with no matching evidence",
        session_repository=repository,
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        discovery_policy=policy,
    )

    assert result.discovery is not None
    assert result.discovery.triggered is True
    assert result.grounded_completion is None
    assert result.narrative is None
    assert result.progress_report is not None
    assert result.progress_report.indexed_evidence_record_ids == ()
    assert result.progress_report.progress_stage is ResearchProgressStage.RESEARCH_REQUIRED
    assert result.progress_report.final is False
    assert result.progress_report.wait_reason is not None
