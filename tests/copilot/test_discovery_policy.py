from __future__ import annotations

from pathlib import Path

import pytest

import knowledge_engine_ai.copilot.discovery_policy as discovery_policy
from knowledge_engine_ai.copilot.discovery_policy import (
    DiscoveryPolicyError,
    FederatedDiscoveryPolicy,
    evaluate_and_run_discovery_augmentation,
)
from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.ke_client import (
    CitationSnowballResult,
    FederatedCandidateSummary,
    FederatedDiscoveryResult,
    GeneralQuestionAcquisitionPlanResult,
    KeCommandError,
)
from knowledge_engine_ai.models import EvidenceReport, EvidenceSummary, RetrievedPaper
from knowledge_engine_ai.orchestrator.parallel_retrieval import (
    ParallelRetrievalResult,
    RetrievalBranchResult,
)
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import ResearchSession, SessionStatus
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection


def _repository_with_session(session_id: str = "sess-1") -> SessionRepository:
    repository = SessionRepository(new_connection(":memory:"))
    repository.create_session(
        ResearchSession(
            schema_version=1,
            session_id=session_id,
            created_at="2026-08-19T00:00:00Z",
            updated_at="2026-08-19T00:00:00Z",
            user_question_original="q",
            status=SessionStatus.RUNNING,
        )
    )
    return repository


def _paper(doi: str, rank: int = 1) -> RetrievedPaper:
    return RetrievedPaper(
        rank=rank,
        paper_id=rank,
        title="T",
        authors="A",
        year="2026",
        journal="J",
        doi=doi,
        source_url="https://example.org",
        license_type="CC BY",
        metadata_source="sources.csv",
        retrieval_score=-1.0,
        retrieval_snippet="s",
        why_matched="m",
        citation="c",
        evidence_records=[],
    )


def _evidence_report(papers: list[RetrievedPaper]) -> EvidenceReport:
    return EvidenceReport(
        schema_version=1,
        question="q",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=0,
            draft=0,
            reviewed=0,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="ready.",
        ),
        papers=papers,
        disclaimer="disclaimer",
    )


def _workflow_result(
    *,
    evidence_report: EvidenceReport | None,
    primary_record_ids: frozenset[str] = frozenset(),
    contradiction_record_ids: frozenset[str] = frozenset(),
    primary_error: str | None = None,
    no_parallel_retrieval: bool = False,
) -> WorkflowResult:
    parallel_retrieval = None
    if not no_parallel_retrieval:
        parallel_retrieval = ParallelRetrievalResult(
            question="q",
            primary=RetrievalBranchResult(query="q", report=evidence_report, error=primary_error),
            contradiction=RetrievalBranchResult(query="q contradiction", report=None, error=None),
            external_discovery_result=None,
            external_discovery_error=None,
            primary_evidence_record_ids=primary_record_ids,
            contradiction_evidence_record_ids=contradiction_record_ids,
            contradiction_only_evidence_record_ids=contradiction_record_ids - primary_record_ids,
        )
    return WorkflowResult(
        session_id="sess-1",
        question="q",
        evidence_report=evidence_report,
        parallel_retrieval=parallel_retrieval,
        steps=(),
    )


def _federated_result(candidate_count: int = 1) -> FederatedDiscoveryResult:
    return FederatedDiscoveryResult(
        search_run_id="run-xyz",
        query_text="q",
        completeness="complete",
        provider_statuses=(),
        candidates=tuple(
            FederatedCandidateSummary(
                canonical_id=f"pubmed:{i}",
                title="T",
                doi=None,
                publication_year=None,
                providers=(),
            )
            for i in range(candidate_count)
        ),
        provider_disagreements=None,
        search_run_created_at=None,
    )


def _acquisition_plan_result(
    search_run_id: str = "run-xyz", research_question_id: str = "rq-abc123"
) -> GeneralQuestionAcquisitionPlanResult:
    return GeneralQuestionAcquisitionPlanResult(
        schema_version=1,
        search_run_id=search_run_id,
        research_question_id=research_question_id,
        query_text="q",
        requested_candidate_count=1,
        resolved_candidate_count=1,
        already_indexed_count=0,
        full_text_selected_count=1,
        metadata_only_count=0,
        skipped_budget_count=0,
        missing_candidate_count=0,
        provider_failures=(),
        items=(),
    )


def _snowball_result(candidate_count: int = 1) -> CitationSnowballResult:
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


# --- FederatedDiscoveryPolicy validation -------------------------------------


def test_policy_rejects_negative_min_evidence_record_coverage(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryPolicyError, match="min_evidence_record_coverage"):
        FederatedDiscoveryPolicy(ledger_root=tmp_path, min_evidence_record_coverage=-1)


@pytest.mark.parametrize("limit", [0, 101])
def test_policy_rejects_an_out_of_range_discovery_limit(tmp_path: Path, limit: int) -> None:
    with pytest.raises(DiscoveryPolicyError, match="discovery_limit_per_provider"):
        FederatedDiscoveryPolicy(ledger_root=tmp_path, discovery_limit_per_provider=limit)


@pytest.mark.parametrize("depth", [0, 4])
def test_policy_rejects_an_out_of_range_snowball_depth(tmp_path: Path, depth: int) -> None:
    with pytest.raises(DiscoveryPolicyError, match="citation_snowball_max_depth"):
        FederatedDiscoveryPolicy(ledger_root=tmp_path, citation_snowball_max_depth=depth)


@pytest.mark.parametrize("seconds", [0, -5, 121.0, float("inf"), float("nan")])
def test_policy_rejects_an_invalid_discovery_execution_budget(
    tmp_path: Path, seconds: float
) -> None:
    with pytest.raises(DiscoveryPolicyError, match="discovery_max_execution_seconds"):
        FederatedDiscoveryPolicy(ledger_root=tmp_path, discovery_max_execution_seconds=seconds)


def test_policy_accepts_conservative_defaults(tmp_path: Path) -> None:
    policy = FederatedDiscoveryPolicy(ledger_root=tmp_path)
    assert (
        policy.min_evidence_record_coverage == discovery_policy.DEFAULT_MIN_EVIDENCE_RECORD_COVERAGE
    )
    assert policy.enable_federated_discovery is True
    assert policy.enable_citation_snowball is True
    # Issue #69 Stage 4: off by default, unlike the two toggles above --
    # see FederatedDiscoveryPolicy's own docstring for why.
    assert policy.enable_acquisition_plan is False
    assert (
        policy.acquisition_plan_max_candidates
        == discovery_policy.DEFAULT_ACQUISITION_PLAN_MAX_CANDIDATES
    )


@pytest.mark.parametrize("max_candidates", [0, 101])
def test_policy_rejects_an_out_of_range_acquisition_plan_max_candidates(
    tmp_path: Path, max_candidates: int
) -> None:
    with pytest.raises(DiscoveryPolicyError, match="acquisition_plan_max_candidates"):
        FederatedDiscoveryPolicy(
            ledger_root=tmp_path, acquisition_plan_max_candidates=max_candidates
        )


def test_policy_rejects_acquisition_plan_full_text_above_max_candidates(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryPolicyError, match="acquisition_plan_max_full_text_acquisitions"):
        FederatedDiscoveryPolicy(
            ledger_root=tmp_path,
            acquisition_plan_max_candidates=5,
            acquisition_plan_max_full_text_acquisitions=6,
        )


@pytest.mark.parametrize("seconds", [0, -5, 121])
def test_policy_rejects_an_invalid_acquisition_plan_max_elapsed_seconds(
    tmp_path: Path, seconds: int
) -> None:
    with pytest.raises(DiscoveryPolicyError, match="acquisition_plan_max_elapsed_seconds"):
        FederatedDiscoveryPolicy(ledger_root=tmp_path, acquisition_plan_max_elapsed_seconds=seconds)


# --- Trigger evaluation -------------------------------------------------------


def test_sufficient_coverage_does_not_trigger_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not attempt any ke subprocess call.")

    monkeypatch.setattr(discovery_policy, "compile_discovery_plan", _fail)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)

    report = _evidence_report([_paper("10.1/a"), _paper("10.1/b")])
    workflow_result = _workflow_result(
        evidence_report=report,
        primary_record_ids=frozenset({"ev-1", "ev-2", "ev-3"}),
    )
    policy = FederatedDiscoveryPolicy(ledger_root=tmp_path, min_evidence_record_coverage=3)
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.triggered is False
    assert result.evidence_record_coverage == 3
    assert "met the configured threshold" in result.trigger_reason
    assert repository.list_events("sess-1") == []


def test_failed_primary_retrieval_does_not_trigger_discovery(tmp_path: Path) -> None:
    workflow_result = _workflow_result(evidence_report=None, primary_error="Core retrieval failed.")
    policy = FederatedDiscoveryPolicy(ledger_root=tmp_path)
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.triggered is False
    assert "Primary corpus retrieval failed" in result.trigger_reason
    assert repository.list_events("sess-1") == []


def test_thin_coverage_triggers_federated_discovery_and_citation_snowball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_discovery: dict[str, object] = {}
    captured_snowball: dict[str, object] = {}

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        captured_discovery["plan"] = plan
        captured_discovery.update(kwargs)
        return _federated_result(candidate_count=2)

    def fake_citation_snowball(
        seed_identifiers: tuple[str, ...], **kwargs: object
    ) -> CitationSnowballResult:
        captured_snowball["seed_identifiers"] = seed_identifiers
        captured_snowball.update(kwargs)
        return _snowball_result()

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", fake_citation_snowball)

    report = _evidence_report([_paper("10.1/a", rank=1), _paper("10.1/b", rank=2)])
    workflow_result = _workflow_result(
        evidence_report=report,
        primary_record_ids=frozenset({"ev-1"}),
    )
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger",
        min_evidence_record_coverage=3,
        citation_snowball_seed_limit=2,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.triggered is True
    assert result.evidence_record_coverage == 1
    assert result.federated_discovery is not None
    assert result.federated_discovery.search_run_id == "run-xyz"
    assert result.federated_discovery_error is None
    assert result.citation_snowball_seed_dois == ("10.1/a", "10.1/b")
    assert captured_snowball["seed_identifiers"] == ("10.1/a", "10.1/b")
    assert result.citation_snowball is not None
    assert result.citation_snowball.snowball_run_id == "snowball-abc"
    assert result.citation_snowball_error is None
    assert result.citation_snowball_skipped_reason is None

    events = repository.list_events("sess-1")
    workflow_nodes = [event.workflow_node for event in events]
    assert workflow_nodes == ["federated_discovery", "citation_snowball"]
    for event in events:
        assert event.source_ids == ()  # discovery leads are never treated as evidence
        assert event.validation_status == "succeeded"


def test_research_question_id_reaches_federated_discovery_but_not_citation_snowball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_discovery: dict[str, object] = {}
    captured_snowball: dict[str, object] = {}

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        captured_discovery.update(kwargs)
        return _federated_result(candidate_count=2)

    def fake_citation_snowball(
        seed_identifiers: tuple[str, ...], **kwargs: object
    ) -> CitationSnowballResult:
        captured_snowball.update(kwargs)
        return _snowball_result()

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", fake_citation_snowball)

    report = _evidence_report([_paper("10.1/a", rank=1)])
    workflow_result = _workflow_result(
        evidence_report=report,
        primary_record_ids=frozenset({"ev-1"}),
    )
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=3
    )
    repository = _repository_with_session()

    evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
        research_question_id="rq-abc123",
    )

    assert captured_discovery["research_question_id"] == "rq-abc123"
    # Citation-snowball has no research_question_id parameter to thread into
    # at all -- see discovery_policy.py's own docstring for why this design
    # deliberately excludes it.
    assert "research_question_id" not in captured_snowball


def test_research_question_id_defaults_to_none_for_existing_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_discovery: dict[str, object] = {}

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        captured_discovery.update(kwargs)
        return _federated_result()

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)

    report = _evidence_report([_paper("10.1/a", rank=1)])
    workflow_result = _workflow_result(
        evidence_report=report,
        primary_record_ids=frozenset({"ev-1"}),
    )
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger", min_evidence_record_coverage=3
    )
    repository = _repository_with_session()

    # No research_question_id supplied -- existing callers of this function
    # keep working unchanged.
    evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert captured_discovery["research_question_id"] is None


def test_no_doi_seeds_skips_citation_snowball_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result()

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)

    report = _evidence_report([_paper("")])  # no DOI
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(ledger_root=tmp_path, min_evidence_record_coverage=3)
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.triggered is True
    assert result.citation_snowball_seed_dois == ()
    assert result.citation_snowball is None
    assert result.citation_snowball_error is None
    assert result.citation_snowball_skipped_reason is not None
    assert "No DOI-bearing paper" in result.citation_snowball_skipped_reason

    events = repository.list_events("sess-1")
    assert [event.workflow_node for event in events] == ["federated_discovery"]


def test_federated_discovery_failure_is_recorded_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        raise KeCommandError("ke federated-discover exited 1: sanitized message")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(ledger_root=tmp_path, min_evidence_record_coverage=3)
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.triggered is True
    assert result.federated_discovery is None
    assert result.federated_discovery_error == "ke federated-discover exited 1: sanitized message"

    events = repository.list_events("sess-1")
    federated_event = next(e for e in events if e.workflow_node == "federated_discovery")
    assert federated_event.validation_status == "failed"
    assert federated_event.notes == "ke federated-discover exited 1: sanitized message"


def test_citation_snowball_disabled_by_policy_is_recorded_as_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result()

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path,
        min_evidence_record_coverage=3,
        enable_citation_snowball=False,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.citation_snowball is None
    assert result.citation_snowball_skipped_reason == "Citation-snowball is disabled by policy."


def test_federated_discovery_disabled_by_policy_still_allows_snowball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_citation_snowball(
        seed_identifiers: tuple[str, ...], **kwargs: object
    ) -> CitationSnowballResult:
        return _snowball_result()

    monkeypatch.setattr(discovery_policy, "citation_snowball", fake_citation_snowball)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path,
        min_evidence_record_coverage=3,
        enable_federated_discovery=False,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.federated_discovery is None
    assert result.federated_discovery_error is None
    assert result.citation_snowball is not None

    events = repository.list_events("sess-1")
    assert [event.workflow_node for event in events] == ["citation_snowball"]


def test_exhausted_shared_execution_budget_is_recorded_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not reach the ke subprocess boundary with no budget left.")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", _fail)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(ledger_root=tmp_path, min_evidence_record_coverage=3)
    repository = _repository_with_session()

    # An already-expired budget: remaining_seconds() raises immediately.
    expired_budget = ExecutionBudget(deadline_monotonic=-1.0)

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=expired_budget,
    )

    assert result.triggered is True
    assert result.federated_discovery is None
    assert result.federated_discovery_error is not None
    assert "execution time limit" in result.federated_discovery_error


# --- Acquisition plan (issue #69 Stage 4) -------------------------------------


def test_acquisition_plan_not_attempted_when_disabled_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not request an acquisition plan when disabled by policy.")

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result(candidate_count=2)

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(discovery_policy, "general_question_acquisition_plan", _fail)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path,
        min_evidence_record_coverage=3,
        enable_citation_snowball=False,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
        research_question_id="rq-abc123",
    )

    assert result.acquisition_plan is None
    assert result.acquisition_plan_attempted is False
    assert result.acquisition_plan_skipped_reason == (
        "Acquisition-plan requests are disabled by policy."
    )
    assert "acquisition_plan" not in [e.workflow_node for e in repository.list_events("sess-1")]


def test_acquisition_plan_skipped_without_federated_discovery_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not request an acquisition plan with no federated result.")

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        raise KeCommandError("ke federated-discover exited 1: sanitized message")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(discovery_policy, "general_question_acquisition_plan", _fail)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path,
        min_evidence_record_coverage=3,
        enable_acquisition_plan=True,
        enable_citation_snowball=False,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
        research_question_id="rq-abc123",
    )

    assert result.acquisition_plan is None
    assert result.acquisition_plan_attempted is False
    assert "nothing to request an acquisition plan against" in (
        result.acquisition_plan_skipped_reason or ""
    )


def test_acquisition_plan_skipped_with_no_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not request an acquisition plan with no candidates.")

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result(candidate_count=0)

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(discovery_policy, "general_question_acquisition_plan", _fail)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path,
        min_evidence_record_coverage=3,
        enable_acquisition_plan=True,
        enable_citation_snowball=False,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
        research_question_id="rq-abc123",
    )

    assert result.acquisition_plan is None
    assert result.acquisition_plan_attempted is False
    assert "returned no candidates" in (result.acquisition_plan_skipped_reason or "")


def test_acquisition_plan_skipped_without_research_question_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Should not request an acquisition plan with no research_question_id.")

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result(candidate_count=2)

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", _fail)
    monkeypatch.setattr(discovery_policy, "general_question_acquisition_plan", _fail)

    report = _evidence_report([_paper("10.1/a")])
    workflow_result = _workflow_result(evidence_report=report, primary_record_ids=frozenset())
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path,
        min_evidence_record_coverage=3,
        enable_acquisition_plan=True,
        enable_citation_snowball=False,
    )
    repository = _repository_with_session()

    # No research_question_id supplied.
    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
    )

    assert result.acquisition_plan is None
    assert result.acquisition_plan_attempted is False
    assert "research_question_id" in (result.acquisition_plan_skipped_reason or "")


def test_acquisition_plan_requested_with_this_runs_own_candidates_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result(candidate_count=3)

    def fake_acquisition_plan(**kwargs: object) -> GeneralQuestionAcquisitionPlanResult:
        captured.update(kwargs)
        return _acquisition_plan_result()

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", lambda *a, **k: _snowball_result())
    monkeypatch.setattr(
        discovery_policy, "general_question_acquisition_plan", fake_acquisition_plan
    )

    report = _evidence_report([_paper("10.1/a", rank=1)])
    workflow_result = _workflow_result(
        evidence_report=report, primary_record_ids=frozenset({"ev-1"})
    )
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path / "ledger",
        min_evidence_record_coverage=3,
        enable_acquisition_plan=True,
        acquisition_plan_max_candidates=2,
        acquisition_plan_max_full_text_acquisitions=2,
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
        research_question_id="rq-abc123",
    )

    assert captured["search_run_id"] == "run-xyz"
    assert captured["research_question_id"] == "rq-abc123"
    # 3 discovered candidates, capped at acquisition_plan_max_candidates=2.
    assert captured["candidate_ids"] == ("pubmed:0", "pubmed:1")
    assert captured["max_candidates"] == 2

    assert result.acquisition_plan is not None
    assert result.acquisition_plan.search_run_id == "run-xyz"
    assert result.acquisition_plan_attempted is True
    assert result.acquisition_plan_error is None
    assert result.acquisition_plan_skipped_reason is None

    events = repository.list_events("sess-1")
    workflow_nodes = [event.workflow_node for event in events]
    assert "acquisition_plan" in workflow_nodes
    acquisition_event = next(e for e in events if e.workflow_node == "acquisition_plan")
    assert acquisition_event.validation_status == "succeeded"
    assert acquisition_event.source_ids == ()  # a plan is still not an Evidence Record


def test_acquisition_plan_failure_is_recorded_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_execute_discovery_plan(plan: object, **kwargs: object) -> FederatedDiscoveryResult:
        return _federated_result(candidate_count=1)

    def fake_acquisition_plan(**kwargs: object) -> GeneralQuestionAcquisitionPlanResult:
        raise KeCommandError("ke general-question-acquisition-plan exited 1: sanitized message")

    monkeypatch.setattr(discovery_policy, "execute_discovery_plan", fake_execute_discovery_plan)
    monkeypatch.setattr(discovery_policy, "citation_snowball", lambda *a, **k: _snowball_result())
    monkeypatch.setattr(
        discovery_policy, "general_question_acquisition_plan", fake_acquisition_plan
    )

    report = _evidence_report([_paper("10.1/a", rank=1)])
    workflow_result = _workflow_result(
        evidence_report=report, primary_record_ids=frozenset({"ev-1"})
    )
    policy = FederatedDiscoveryPolicy(
        ledger_root=tmp_path, min_evidence_record_coverage=3, enable_acquisition_plan=True
    )
    repository = _repository_with_session()

    result = evaluate_and_run_discovery_augmentation(
        session_repository=repository,
        session_id="sess-1",
        workflow_result=workflow_result,
        policy=policy,
        execution_budget=None,
        research_question_id="rq-abc123",
    )

    assert result.acquisition_plan is None
    assert result.acquisition_plan_attempted is True
    assert result.acquisition_plan_error == (
        "ke general-question-acquisition-plan exited 1: sanitized message"
    )
    assert result.acquisition_plan_skipped_reason is None

    events = repository.list_events("sess-1")
    acquisition_event = next(e for e in events if e.workflow_node == "acquisition_plan")
    assert acquisition_event.validation_status == "failed"
    assert acquisition_event.notes == (
        "ke general-question-acquisition-plan exited 1: sanitized message"
    )
