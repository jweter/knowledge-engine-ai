from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import knowledge_engine_ai.cli as cli
from knowledge_engine_ai.cli import app
from knowledge_engine_ai.copilot.discovery_policy import FederatedDiscoveryPolicy
from knowledge_engine_ai.copilot.intent import ISAValidationResult
from knowledge_engine_ai.copilot.run_research_question import ResearchQuestionResult
from knowledge_engine_ai.ke_client import KeCommandError
from knowledge_engine_ai.models import (
    ClaimConfidence,
    EvidenceConsensus,
    EvidenceCoverage,
    EvidenceIntelligence,
    EvidenceQuality,
    EvidenceRecord,
    EvidenceReport,
    EvidenceSummary,
    RetrievedPaper,
)
from knowledge_engine_ai.orchestrator.close_gate import SessionCloseResult
from knowledge_engine_ai.orchestrator.observability import SessionTrace
from knowledge_engine_ai.orchestrator.verification import VerificationResult
from knowledge_engine_ai.orchestrator.workflow import WorkflowResult
from knowledge_engine_ai.sessions.models import SessionStatus


def _unwrapped(output: str) -> str:
    """Collapse Rich's line-wrapping so substring assertions survive it."""

    return " ".join(output.split())


def _report(*, papers: list[RetrievedPaper] | None = None) -> EvidenceReport:
    return EvidenceReport(
        schema_version=1,
        question="does semaglutide reduce lean mass",
        sources_path="sources.csv",
        evidence_path="evidence.jsonl",
        evidence_summary=EvidenceSummary(
            total=1,
            draft=1,
            reviewed=0,
            needs_revision=0,
            rejected=0,
            unspecified=0,
            readiness_note="draft only; secondary review needed.",
        ),
        papers=papers if papers is not None else [],
        disclaimer="This report is retrieval plus recorded evidence only.",
    )


def test_ask_prints_a_compact_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = RetrievedPaper(
        rank=1,
        paper_id=42,
        title="A Trial of Semaglutide",
        authors="A. Author",
        year="2026",
        journal="A Journal",
        doi="10.1000/example",
        source_url="https://example.org",
        license_type="CC BY",
        metadata_source="corpus sources.csv",
        retrieval_score=-5.1,
        retrieval_snippet="semaglutide reduced lean mass",
        why_matched="Matched indexed title, abstract, or body text using: semaglutide",
        citation="A Trial of Semaglutide. (2026).",
        evidence_records=[
            EvidenceRecord(
                evidence_record_id="ev-1",
                extraction_method="manual_human_review",
                extraction_status="draft_manual_prototype",
                review_status="draft",
                review_checklist=None,
                review_notes=None,
                evidence_direction="supports",
                research_question=None,
                claim_text="Semaglutide reduced lean mass.",
                population=None,
                intervention=None,
                comparator=None,
                outcome=None,
                result_summary=None,
                limitations=[],
                uncertainty_notes=None,
                confidence_note=None,
                source_span=None,
            )
        ],
    )
    monkeypatch.setattr(
        cli, "enriched_evidence_report", lambda *args, **kwargs: _report(papers=[paper])
    )
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0
    unwrapped = _unwrapped(result.output)
    assert "A Trial of Semaglutide" in unwrapped
    assert "10.1000/example" in unwrapped
    assert "Semaglutide reduced lean mass." in unwrapped
    assert "retrieval plus recorded evidence only" in unwrapped


def test_ask_reports_no_papers_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "enriched_evidence_report", lambda *args, **kwargs: _report(papers=[]))
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0
    assert "No relevant papers found" in _unwrapped(result.output)


def test_ask_exits_nonzero_and_prints_the_error_on_a_ke_command_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_evidence_report(*args: object, **kwargs: object) -> EvidenceReport:
        raise KeCommandError("ke evidence-report exited 1: No relevant papers found.")

    monkeypatch.setattr(cli, "enriched_evidence_report", fake_evidence_report)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 1
    assert "No relevant papers found" in _unwrapped(result.output)


def test_ask_fails_for_a_missing_sources_file(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(tmp_path / "does-not-exist.csv"),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code != 0


def _paper_with_intelligence() -> RetrievedPaper:
    intelligence = EvidenceIntelligence(
        schema_version=1,
        evidence_record_id="ev-1",
        claim_id=1,
        evidence_quality=EvidenceQuality(
            score=94,
            study_design_tier="randomized_controlled_trial",
            manually_reviewed=True,
            extraction_tier="manual",
        ),
        evidence_consensus=EvidenceConsensus(
            relationship_edge_count=2,
            supports_count=2,
            contradicts_count=0,
            agreement_total=2,
            score=100,
            reliability="moderate",
        ),
        claim_confidence=ClaimConfidence(score=89, reliability="moderate"),
        evidence_coverage=EvidenceCoverage(
            records_in_relationship=7, total_records=155, percentage=5
        ),
        synthesis=["Evidence Quality: 94/100.", "Evidence Consensus: 100/100."],
        scope_note="Every number above is computed deterministically.",
    )
    return RetrievedPaper(
        rank=1,
        paper_id=42,
        title="A Trial of Semaglutide",
        authors="A. Author",
        year="2026",
        journal="A Journal",
        doi="10.1000/example",
        source_url="https://example.org",
        license_type="CC BY",
        metadata_source="corpus sources.csv",
        retrieval_score=-5.1,
        retrieval_snippet="semaglutide reduced lean mass",
        why_matched="Matched indexed title, abstract, or body text using: semaglutide",
        citation="A Trial of Semaglutide. (2026).",
        evidence_records=[
            EvidenceRecord(
                evidence_record_id="ev-1",
                extraction_method="manual_human_review",
                extraction_status="draft_manual_prototype",
                review_status="draft",
                review_checklist=None,
                review_notes=None,
                evidence_direction="supports",
                research_question=None,
                claim_text="Semaglutide reduced lean mass.",
                population=None,
                intervention=None,
                comparator=None,
                outcome=None,
                result_summary=None,
                limitations=[],
                uncertainty_notes=None,
                confidence_note=None,
                source_span=None,
                evidence_intelligence=intelligence,
            )
        ],
    )


def test_ask_shows_evidence_intelligence_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0, result.output
    unwrapped = _unwrapped(result.output)
    assert "Evidence Quality: 94/100" in unwrapped
    assert "Evidence Consensus: 100 (moderate)" in unwrapped
    assert "Claim Confidence: 89 (moderate)" in unwrapped


def test_ask_format_json_prints_valid_structured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    record = payload["papers"][0]["evidence_records"][0]
    assert record["evidence_intelligence"]["evidence_quality"]["score"] == 94
    assert record["evidence_intelligence"]["claim_confidence"]["score"] == 89


class _FakeLLM:
    def __init__(self, *, model: str, host: str) -> None:
        self.model = model
        self.host = host

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 400,
        timeout_seconds: float | None = None,
    ) -> str:
        del timeout_seconds
        assert "does semaglutide reduce lean mass" in prompt
        return "Semaglutide reduced lean mass [ev-1]."


def test_ask_synthesize_requires_a_model_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KE_AI_LLM_MODEL", raising=False)
    monkeypatch.setattr(cli, "enriched_evidence_report", lambda *args, **kwargs: _report(papers=[]))
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--synthesize",
        ],
    )

    assert result.exit_code == 1
    assert "--llm-model or KE_AI_LLM_MODEL" in _unwrapped(result.output)


def test_ask_synthesize_prints_the_grounded_narrative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--synthesize",
            "--llm-model",
            "qwen2.5:1.5b",
        ],
    )

    assert result.exit_code == 0, result.output
    unwrapped = _unwrapped(result.output)
    assert "AI-generated synthesis" in unwrapped
    assert "Semaglutide reduced lean mass [ev-1]." in unwrapped


def test_ask_synthesize_reads_the_model_name_from_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setenv("KE_AI_LLM_MODEL", "qwen2.5:1.5b")
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--synthesize",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "AI-generated synthesis" in _unwrapped(result.output)


def test_ask_synthesize_passes_the_ollama_host_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_hosts: list[str] = []

    class _RecordingFakeLLM:
        def __init__(self, *, model: str, host: str) -> None:
            seen_hosts.append(host)

        def generate(
            self,
            prompt: str,
            *,
            max_tokens: int = 400,
            timeout_seconds: float | None = None,
        ) -> str:
            del timeout_seconds
            return "Semaglutide reduced lean mass [ev-1]."

    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    monkeypatch.setattr(cli, "OllamaLLM", _RecordingFakeLLM)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--synthesize",
            "--llm-model",
            "qwen2.5:1.5b",
            "--ollama-host",
            "http://192.168.1.50:11434",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen_hosts == ["http://192.168.1.50:11434"]


def test_ask_synthesize_json_includes_the_synthesis_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "enriched_evidence_report",
        lambda *args, **kwargs: _report(papers=[_paper_with_intelligence()]),
    )
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--synthesize",
            "--llm-model",
            "qwen2.5:1.5b",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["synthesis"] == "Semaglutide reduced lean mass [ev-1]."


def test_ask_without_synthesize_flag_never_touches_the_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_if_constructed(*, model: str, host: str) -> _FakeLLM:
        raise AssertionError("OllamaLLM should not be constructed without --synthesize")

    monkeypatch.setattr(cli, "enriched_evidence_report", lambda *args, **kwargs: _report(papers=[]))
    monkeypatch.setattr(cli, "OllamaLLM", _fail_if_constructed)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code == 0, result.output


def test_ask_rejects_an_invalid_format(tmp_path: Path) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "ask",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--format",
            "xml",
        ],
    )

    assert result.exit_code != 0


def _research_result(
    *,
    narrative: str | None = "Semaglutide reduced lean mass [ev-1].",
    synthesis_error: str | None = None,
    close_status: SessionStatus = SessionStatus.COMPLETED,
    unresolved_required_criteria: tuple[str, ...] = (),
) -> ResearchQuestionResult:
    verification = (
        None
        if narrative is None
        else VerificationResult(
            narrative=narrative,
            hallucinated_citations=(),
            ungrounded_numbers=(),
            missed_qualifiers=(),
        )
    )
    workflow = WorkflowResult(
        session_id="sess-research-1",
        question="does semaglutide reduce lean mass",
        evidence_report=None,
        parallel_retrieval=None,
        steps=(),
    )
    trace = SessionTrace(
        session_id="sess-research-1",
        question="does semaglutide reduce lean mass",
        events=(),
        failed_events=(),
        total_duration_ms=None,
        evidence_record_ids=(),
    )
    return ResearchQuestionResult(
        session_id="sess-research-1",
        question="does semaglutide reduce lean mass",
        workflow=workflow,
        discovery=None,
        narrative=narrative,
        synthesis_error=synthesis_error,
        verification=verification,
        session_report=None,
        close_result=SessionCloseResult(
            session_id="sess-research-1",
            status=close_status,
            validation=ISAValidationResult(
                complete=not unresolved_required_criteria,
                unresolved_required_criteria=unresolved_required_criteria,
            ),
        ),
        trace=trace,
    )


def test_research_requires_a_model_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.delenv("KE_AI_LLM_MODEL", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
        ],
    )

    assert result.exit_code != 0
    assert "requires --llm-model" in result.output


def test_research_prints_narrative_and_session_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setattr(cli, "run_research_question", lambda *args, **kwargs: _research_result())

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
        ],
    )

    assert result.exit_code == 0, result.output
    unwrapped = _unwrapped(result.output)
    assert "sess-research-1" in unwrapped
    assert "Semaglutide reduced lean mass [ev-1]." in unwrapped
    assert "Skeptic verification: clean" in unwrapped
    assert "Session status:" in unwrapped
    assert "completed" in unwrapped


def test_research_reports_a_blocked_session_and_unresolved_criteria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setattr(
        cli,
        "run_research_question",
        lambda *args, **kwargs: _research_result(
            close_status=SessionStatus.BLOCKED,
            unresolved_required_criteria=("citation_integrity",),
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
        ],
    )

    assert result.exit_code == 0, result.output
    unwrapped = _unwrapped(result.output)
    assert "blocked" in unwrapped
    assert "citation_integrity" in unwrapped
    assert "Draft narrative withheld" in unwrapped
    assert "Semaglutide reduced lean mass [ev-1]." not in unwrapped


def test_research_format_json_includes_expected_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setattr(cli, "run_research_question", lambda *args, **kwargs: _research_result())

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["session_id"] == "sess-research-1"
    assert payload["narrative"] == "Semaglutide reduced lean mass [ev-1]."
    assert payload["narrative_releaseable"] is True
    assert payload["close_status"] == "completed"
    assert payload["close_complete"] is True
    assert payload["verification"]["is_clean"] is True


def test_research_no_narrative_prints_explanation_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setattr(
        cli, "run_research_question", lambda *args, **kwargs: _research_result(narrative=None)
    )

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "No evidence with a stated claim was retrieved to narrate" in _unwrapped(result.output)


# --- `research --broaden-search-on-gap` (AI-FRD-3/AI-FRD-4 wiring) -----------


def test_research_broaden_search_on_gap_requires_discovery_ledger_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setattr(cli, "run_research_question", lambda *args, **kwargs: _research_result())

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
            "--broaden-search-on-gap",
        ],
    )

    assert result.exit_code != 0
    assert "requires --discovery-ledger-root" in result.output


def test_research_broaden_search_on_gap_passes_a_policy_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)

    captured: dict[str, object] = {}

    def fake_run_research_question(*args: object, **kwargs: object) -> ResearchQuestionResult:
        captured.update(kwargs)
        return _research_result()

    monkeypatch.setattr(cli, "run_research_question", fake_run_research_question)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
            "--broaden-search-on-gap",
            "--discovery-ledger-root",
            str(tmp_path / "ledger"),
        ],
    )

    assert result.exit_code == 0, result.output
    policy = captured["discovery_policy"]
    assert isinstance(policy, FederatedDiscoveryPolicy)
    assert policy.ledger_root == tmp_path / "ledger"


def test_research_without_broaden_search_on_gap_passes_no_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)

    captured: dict[str, object] = {}

    def fake_run_research_question(*args: object, **kwargs: object) -> ResearchQuestionResult:
        captured.update(kwargs)
        return _research_result()

    monkeypatch.setattr(cli, "run_research_question", fake_run_research_question)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["discovery_policy"] is None


def test_research_format_json_includes_null_discovery_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("")
    evidence.write_text("")
    monkeypatch.setattr(cli, "OllamaLLM", _FakeLLM)
    monkeypatch.setattr(cli, "run_research_question", lambda *args, **kwargs: _research_result())

    result = CliRunner().invoke(
        app,
        [
            "research",
            "does semaglutide reduce lean mass",
            "--sources",
            str(sources),
            "--evidence",
            str(evidence),
            "--llm-model",
            "qwen2.5:1.5b",
            "--session-db",
            str(tmp_path / "sessions.db"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["discovery"] is None
