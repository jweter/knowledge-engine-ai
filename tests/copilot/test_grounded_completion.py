from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import (
    GroundedCompletionPolicy,
    complete_discovered_research,
)
from knowledge_engine_ai.ke_client import (
    GeneralQuestionAcquisitionIdentity,
    GeneralQuestionAcquisitionItem,
    GeneralQuestionAcquisitionPlanResult,
)
from knowledge_engine_ai.models import EvidenceReport


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _plan(*items: GeneralQuestionAcquisitionItem) -> GeneralQuestionAcquisitionPlanResult:
    return GeneralQuestionAcquisitionPlanResult(
        schema_version=1,
        search_run_id="run-1",
        research_question_id="rq-1",
        query_text="Monster Energy blood pressure",
        requested_candidate_count=len(items),
        resolved_candidate_count=len(items),
        already_indexed_count=sum(item.disposition == "already_indexed" for item in items),
        full_text_selected_count=sum(item.disposition == "eligible_full_text" for item in items),
        metadata_only_count=0,
        skipped_budget_count=0,
        missing_candidate_count=0,
        provider_failures=(),
        items=tuple(items),
    )


def _item(
    candidate_id: str,
    *,
    disposition: str,
    route: str | None = None,
    paper_id: int | None = None,
) -> GeneralQuestionAcquisitionItem:
    return GeneralQuestionAcquisitionItem(
        candidate_id=candidate_id,
        title=f"Paper {candidate_id}",
        disposition=disposition,
        identity=GeneralQuestionAcquisitionIdentity(
            canonical_id=candidate_id,
            doi=f"10.1000/{candidate_id}",
            pmid="12345",
            pmcid="PMC12345",
            arxiv_id=None,
            openalex_id=None,
            semantic_scholar_id=None,
        ),
        selected_observation_provider="pubmed",
        acquisition_route=route,
        full_text_url="https://example.invalid/paper.pdf" if route else None,
        xml_url=None,
        license="CC BY" if route else None,
        open_access=True if route else None,
        existing_paper_id=paper_id,
        reason=None,
    )


def _discovery(plan: GeneralQuestionAcquisitionPlanResult | None) -> DiscoveryAugmentationResult:
    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason="coverage gap",
        evidence_record_coverage=0,
        acquisition_plan=plan,
        acquisition_plan_attempted=plan is not None,
        acquisition_plan_skipped_reason=None if plan is not None else "not available",
    )


def _policy(tmp_path: Path) -> GroundedCompletionPolicy:
    core_root = tmp_path / "core"
    (core_root / "data" / "federated_search_runs").mkdir(parents=True)
    return GroundedCompletionPolicy(
        papers_dir=core_root / "data" / "papers",
        grounding_model="test-grounder",
        core_working_directory=core_root,
        max_promoted_records=2,
    )


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def test_completion_skips_cleanly_without_an_acquisition_plan(tmp_path: Path) -> None:
    result = complete_discovered_research(
        "Does Monster Energy raise blood pressure?",
        discovery=_discovery(None),
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        policy=_policy(tmp_path),
    )

    assert result.attempted is False
    assert result.reretrieval_report is None
    assert result.skipped_reason == "not available"


def test_completion_acquires_grounds_promotes_and_reretrieves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine_ai.copilot import grounded_completion as module

    commands: list[list[str]] = []
    policy = _policy(tmp_path)
    evidence = tmp_path / "evidence.jsonl"
    sources = tmp_path / "sources.csv"
    sources.write_text("title,doi\n", encoding="utf-8")
    plan = _plan(
        _item("existing", disposition="already_indexed", paper_id=7),
        _item("new-pmc", disposition="eligible_full_text", route="pmc_oa"),
    )

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        commands.append(command)
        operation = command[1]
        if operation == "general-question-acquire-pmc":
            request = json.loads(Path(command[2]).read_text(encoding="utf-8"))
            receipt_path = Path(command[command.index("--receipt") + 1])
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "search_run_id": request["search_run_id"],
                        "research_question_id": request["research_question_id"],
                        "acquisition_route": "pmc_oa",
                        "import_run_id": "import-1",
                        "parsed_count": 1,
                        "persisted_count": 1,
                        "reused_count": 0,
                        "items": [
                            {
                                "candidate_id": "new-pmc",
                                "paper_id": 9,
                                "persistence_status": "persisted",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        elif operation == "extraction-review-batch-generate":
            output = Path(command[command.index("--output") + 1])
            _write_jsonl(
                output,
                [
                    {
                        "claim_text": "Blood pressure increased by 4%.",
                        "result_summary": "Blood pressure increased by 4%.",
                        "source_span": {"paper_id": 9, "page_number": 1},
                    },
                    {
                        "claim_text": "A second claim increased by 2%.",
                        "result_summary": "A second claim increased by 2%.",
                        "source_span": {"paper_id": 7, "page_number": 1},
                    },
                ],
            )
        elif operation == "extraction-review-autoclassify":
            input_path = Path(command[command.index("--input") + 1])
            output = Path(command[command.index("--output") + 1])
            drafts = [json.loads(line) for line in input_path.read_text().splitlines() if line]
            classified = []
            for index, draft in enumerate(drafts, start=1):
                classified.append(
                    {
                        **draft,
                        "schema_version": None,
                        "evidence_record_id": None,
                        "extraction_method": "m52-evidence-classification-v1",
                        "extraction_status": "draft_review_required",
                        "source_doi": f"10.1000/paper-{index}",
                        "source_title": f"Paper {index}",
                        "source_type": "paper",
                        "study_type": "randomized_controlled_trial",
                        "research_question": "Mechanical paper question",
                        "evidence_direction": "supports",
                        "population": "adults",
                        "intervention": "energy drink",
                        "comparator": "control",
                        "outcome": "blood pressure",
                        "limitations": [],
                        "uncertainty_notes": "automated",
                        "confidence_note": "no confidence rating",
                        "provenance": {"created_by": "test"},
                        "created_for_milestone": "M52",
                        "review_status": "draft",
                        "review_checklist": {"automated_classification": True},
                    }
                )
            _write_jsonl(output, classified)
        elif operation == "extraction-review-promote":
            input_path = Path(command[command.index("--input") + 1])
            output = Path(command[command.index("--output") + 1])
            input_records = [
                json.loads(line) for line in input_path.read_text().splitlines() if line
            ]
            existing = (
                [json.loads(line) for line in output.read_text().splitlines() if line]
                if output.exists()
                else []
            )
            existing_ids = {record.get("evidence_record_id") for record in existing}
            promoted = []
            for index, record in enumerate(input_records, start=1):
                completed = dict(record)
                completed["schema_version"] = completed.get("schema_version") or "0.1"
                completed["evidence_record_id"] = completed.get("evidence_record_id") or f"ev-{index}"
                completed["review_status"] = completed.get("review_status") or "draft"
                if completed["evidence_record_id"] not in existing_ids:
                    promoted.append(completed)
            _write_jsonl(output, [*existing, *promoted])
        elif operation == "evidence-review-automate":
            staged = Path(command[command.index("--evidence") + 1])
            record_id = command[command.index("--evidence-record-id") + 1]
            records = [json.loads(line) for line in staged.read_text().splitlines() if line]
            for record in records:
                if record["evidence_record_id"] == record_id:
                    record["extraction_method"] = "m69-llm-grounded-pico-v1"
                    record["review_checklist"] = {
                        **record.get("review_checklist", {}),
                        "llm_grounded": True,
                        "human_reviewed": False,
                    }
            _write_jsonl(staged, records)
        elif operation == "evidence-record-review-promote":
            staged = Path(command[command.index("--evidence") + 1])
            records = [json.loads(line) for line in staged.read_text().splitlines() if line]
            for record in records:
                if record.get("review_checklist", {}).get("llm_grounded") is True:
                    record["review_status"] = "reviewed"
            _write_jsonl(staged, records)
        return _Completed()

    reretrieved = cast(EvidenceReport, object())
    monkeypatch.setattr(module, "_run_ke_command", fake_run)
    monkeypatch.setattr(module, "_resolve_ke_executable", lambda name: name)
    monkeypatch.setattr(module, "evidence_report", lambda *args, **kwargs: reretrieved)

    result = complete_discovered_research(
        "Does Monster Energy raise blood pressure?",
        discovery=_discovery(plan),
        sources=sources,
        evidence=evidence,
        policy=policy,
    )

    assert result.attempted is True
    assert result.already_indexed_paper_ids == (7,)
    assert result.paper_ids == (7, 9)
    assert result.promoted_record_ids == ("ev-1", "ev-2")
    assert result.grounded_record_ids == ("ev-1", "ev-2")
    assert result.reretrieval_report is reretrieved
    assert result.completed_with_new_evidence is True
    assert [command[1] for command in commands] == [
        "general-question-acquire-pmc",
        "extraction-review-batch-generate",
        "extraction-review-autoclassify",
        "extraction-review-promote",
        "evidence-review-automate",
        "evidence-review-automate",
        "evidence-record-review-promote",
        "extraction-review-promote",
    ]


def test_completion_does_not_persist_an_ungrounded_staged_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine_ai.copilot import grounded_completion as module

    policy = _policy(tmp_path)
    evidence = tmp_path / "evidence.jsonl"
    plan = _plan(_item("existing", disposition="already_indexed", paper_id=7))

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        operation = command[1]
        if operation == "extraction-review-batch-generate":
            output = Path(command[command.index("--output") + 1])
            _write_jsonl(output, [{"claim_text": "A result was 5% higher."}])
        elif operation == "extraction-review-autoclassify":
            output = Path(command[command.index("--output") + 1])
            _write_jsonl(
                output,
                [
                    {
                        "schema_version": None,
                        "evidence_record_id": None,
                        "claim_text": "A result was 5% higher.",
                        "result_summary": "A result was 5% higher.",
                    }
                ],
            )
        elif operation == "extraction-review-promote":
            input_path = Path(command[command.index("--input") + 1])
            output = Path(command[command.index("--output") + 1])
            record = json.loads(input_path.read_text().splitlines()[0])
            record["evidence_record_id"] = "ev-raw"
            record["review_status"] = "draft"
            record["review_checklist"] = {}
            _write_jsonl(output, [record])
        elif operation == "evidence-review-automate":
            return _Completed(returncode=1, stderr="grounding failed")
        elif operation == "evidence-record-review-promote":
            return _Completed()
        return _Completed()

    monkeypatch.setattr(module, "_run_ke_command", fake_run)
    monkeypatch.setattr(module, "_resolve_ke_executable", lambda name: name)

    result = complete_discovered_research(
        "Question?",
        discovery=_discovery(plan),
        sources=tmp_path / "sources.csv",
        evidence=evidence,
        policy=policy,
    )

    assert result.grounding_failures == ("ev-raw",)
    assert result.promoted_record_ids == ()
    assert result.reretrieval_report is None
    assert not evidence.exists()
