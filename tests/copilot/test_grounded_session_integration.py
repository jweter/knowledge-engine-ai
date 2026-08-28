from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_engine_ai.copilot.run_research_question as run_module
from knowledge_engine_ai.copilot.discovery_policy import (
    DiscoveryAugmentationResult,
    FederatedDiscoveryPolicy,
)
from knowledge_engine_ai.copilot.grounded_completion import (
    GroundedCompletionPolicy,
    GroundedCompletionResult,
)
from knowledge_engine_ai.ke_client import FederatedDiscoveryResult
from knowledge_engine_ai.models import EvidenceReport, parse_evidence_report
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection


class _FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del max_tokens, timeout_seconds
        self.prompts.append(prompt)
        return self.response


def _repository() -> SessionRepository:
    return SessionRepository(new_connection(":memory:"))


def _report(
    evidence_record_id: str | None,
    *,
    claim_text: str = "A grounded result was observed.",
    doi: str = "10.1000/example",
) -> EvidenceReport:
    records: list[dict[str, object]] = []
    papers: list[dict[str, object]] = []
    if evidence_record_id is not None:
        records.append(
            {
                "evidence_record_id": evidence_record_id,
                "claim_text": claim_text,
                "evidence_direction": "supports",
            }
        )
        papers.append(
            {
                "rank": 1,
                "paper_id": 1,
                "title": "Grounded paper",
                "authors": "A. Author",
                "year": "2026",
                "journal": "Journal",
                "doi": doi,
                "source_url": "https://example.org",
                "license_type": "CC BY",
                "metadata_source": "sources.csv",
                "retrieval_score": -1.0,
                "retrieval_snippet": claim_text,
                "why_matched": "matched",
                "citation": "A. Author (2026)",
                "evidence_records": records,
            }
        )
    payload = {
        "schema_version": 1,
        "question": "q",
        "sources_path": "sources.csv",
        "evidence_path": "evidence.jsonl",
        "evidence_summary": {
            "total": len(records),
            "draft": 0,
            "reviewed": len(records),
            "needs_revision": 0,
            "rejected": 0,
            "unspecified": 0,
            "readiness_note": "ready" if records else "no records",
        },
        "papers": papers,
        "disclaimer": "retrieval plus recorded evidence only",
    }
    return parse_evidence_report(payload)


def _workflow(question: str, report: EvidenceReport | None) -> WorkflowResult:
    return WorkflowResult(
        session_id="workflow-session",
        question=question,
        evidence_report=report,
        parallel_retrieval=None,
        steps=(),
    )


def _discovery(question: str) -> DiscoveryAugmentationResult:
    federated = FederatedDiscoveryResult(
        search_run_id="search-run-1",
        query_text=question,
        completeness="complete",
        provider_statuses=(),
        candidates=(),
        provider_disagreements=None,
        search_run_created_at=None,
    )
    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason="initial evidence coverage was thin",
        evidence_record_coverage=0,
        federated_discovery=federated,
        federated_discovery_attempted=True,
        acquisition_plan_attempted=True,
    )


def _policies(tmp_path: Path) -> tuple[FederatedDiscoveryPolicy, GroundedCompletionPolicy]:
    ledger_root = tmp_path / "ledger"
    return (
        FederatedDiscoveryPolicy(
            ledger_root=ledger_root,
            min_evidence_record_coverage=3,
            enable_acquisition_plan=True,
        ),
        GroundedCompletionPolicy(
            ledger_root=ledger_root,
            papers_dir=tmp_path / "papers",
            grounding_model="fake-grounding-model",
            core_working_directory=tmp_path,
        ),
    )


def test_grounded_reretrieval_replaces_initial_report_for_synthesis_in_same_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "does the new treatment work"
    initial_report = _report("ev-old", claim_text="Old local-corpus result.")
    reretrieval_report = _report("ev-new", claim_text="Newly grounded discovered result.")
    discovery_policy, completion_policy = _policies(tmp_path)
    repository = _repository()
    llm = _FakeLLM("Newly grounded discovered result [ev-new].")

    monkeypatch.setattr(
        run_module,
        "run_fixed_evidence_workflow",
        lambda **kwargs: _workflow(question, initial_report),
    )
    monkeypatch.setattr(
        run_module,
        "evaluate_and_run_discovery_augmentation",
        lambda **kwargs: _discovery(question),
    )
    completion = GroundedCompletionResult(
        attempted=True,
        search_run_id="search-run-1",
        research_question_id="rq-test",
        already_indexed_paper_ids=(2,),
        paper_ids=(2,),
        draft_item_count=4,
        classified_item_count=3,
        staged_record_ids=("ev-new",),
        grounded_record_ids=("ev-new",),
        promoted_record_ids=("ev-new",),
        reretrieval_report=reretrieval_report,
    )
    monkeypatch.setattr(
        run_module,
        "complete_discovered_research",
        lambda *args, **kwargs: completion,
    )

    result = run_module.run_research_question(
        question,
        session_repository=repository,
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        llm=llm,
        discovery_policy=discovery_policy,
        grounded_completion_policy=completion_policy,
        research_question_id="rq-test",
    )

    assert result.grounded_completion is completion
    assert result.used_reretrieved_evidence is True
    assert result.effective_evidence_report is reretrieval_report
    assert result.narrative == "Newly grounded discovered result [ev-new]."
    assert result.verification is not None and result.verification.is_clean
    assert result.close_result.status is SessionStatus.COMPLETED
    assert llm.prompts
    assert "ev-new" in llm.prompts[0]
    assert "ev-old" not in llm.prompts[0]

    events = repository.list_events(result.session_id)
    workflow_nodes = [event.workflow_node for event in events]
    assert workflow_nodes == [
        "grounded_acquisition",
        "grounded_extraction",
        "grounded_reretrieval",
        "synthesis",
        "research_isa_close_gate",
    ]
    reretrieval_event = next(
        event for event in events if event.workflow_node == "grounded_reretrieval"
    )
    assert reretrieval_event.source_ids == ("ev-new",)
    assert reretrieval_event.source_dois == ("10.1000/example",)
    assert result.trace.evidence_record_ids == ("ev-new",)

    criterion = next(
        item
        for item in repository.latest_criterion_results(result.session_id)
        if item.criterion_id == "grounded_completion_integrity"
    )
    assert criterion.status.value == "passed"


def test_grounded_extraction_failure_is_durable_and_blocks_session_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "a thin-coverage question"
    discovery_policy, completion_policy = _policies(tmp_path)
    repository = _repository()
    llm = _FakeLLM("should never be used")

    monkeypatch.setattr(
        run_module,
        "run_fixed_evidence_workflow",
        lambda **kwargs: _workflow(question, _report(None)),
    )
    monkeypatch.setattr(
        run_module,
        "evaluate_and_run_discovery_augmentation",
        lambda **kwargs: _discovery(question),
    )
    completion = GroundedCompletionResult(
        attempted=True,
        search_run_id="search-run-1",
        research_question_id="rq-test",
        already_indexed_paper_ids=(2,),
        paper_ids=(2,),
        extraction_error="grounded extraction failed",
    )
    monkeypatch.setattr(
        run_module,
        "complete_discovered_research",
        lambda *args, **kwargs: completion,
    )

    result = run_module.run_research_question(
        question,
        session_repository=repository,
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        llm=llm,
        discovery_policy=discovery_policy,
        grounded_completion_policy=completion_policy,
        research_question_id="rq-test",
    )

    assert result.used_reretrieved_evidence is False
    assert result.narrative is None
    assert llm.prompts == []
    assert result.close_result.status is SessionStatus.BLOCKED
    assert (
        "grounded_completion_integrity"
        in result.close_result.validation.unresolved_required_criteria
    )

    events = repository.list_events(result.session_id)
    extraction_event = next(
        event for event in events if event.workflow_node == "grounded_extraction"
    )
    assert extraction_event.validation_status == "failed"
    assert extraction_event.notes == "Grounded extraction failed: grounded extraction failed"
    assert "grounded_extraction" in [event.workflow_node for event in result.trace.failed_events]


def test_grounded_completion_requires_acquisition_enabled_discovery_policy(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    completion_policy = GroundedCompletionPolicy(
        ledger_root=ledger_root,
        papers_dir=tmp_path / "papers",
        grounding_model="fake",
    )

    with pytest.raises(ValueError, match="requires discovery_policy"):
        run_module.run_research_question(
            "q",
            session_repository=_repository(),
            sources=tmp_path / "sources.csv",
            evidence=tmp_path / "evidence.jsonl",
            llm=_FakeLLM("unused"),
            grounded_completion_policy=completion_policy,
        )

    discovery_policy = FederatedDiscoveryPolicy(ledger_root=ledger_root)
    with pytest.raises(ValueError, match="enable_acquisition_plan=True"):
        run_module.run_research_question(
            "q",
            session_repository=_repository(),
            sources=tmp_path / "sources.csv",
            evidence=tmp_path / "evidence.jsonl",
            llm=_FakeLLM("unused"),
            discovery_policy=discovery_policy,
            grounded_completion_policy=completion_policy,
        )
