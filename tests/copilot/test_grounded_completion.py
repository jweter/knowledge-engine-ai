from __future__ import annotations

import json
import time
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


def _policy(tmp_path: Path, **overrides: object) -> GroundedCompletionPolicy:
    core_root = tmp_path / "core"
    ledger_root = core_root / "data" / "federated_search_runs"
    ledger_root.mkdir(parents=True)
    kwargs: dict[str, object] = {
        "ledger_root": ledger_root,
        "papers_dir": core_root / "data" / "papers",
        "grounding_model": "test-grounder",
        "core_working_directory": core_root,
        "max_promoted_records": 2,
        "min_promoted_records_for_early_stop": 2,
    }
    kwargs.update(overrides)
    return GroundedCompletionPolicy(**kwargs)  # type: ignore[arg-type]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


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


_CLAIMS_BY_PAPER_ID: dict[int, dict[str, object]] = {
    7: {
        "claim_text": "A second claim increased by 2%.",
        "result_summary": "A second claim increased by 2%.",
        "source_span": {"paper_id": 7, "page_number": 1},
    },
    8: {
        "claim_text": "A third claim increased by 3%.",
        "result_summary": "A third claim increased by 3%.",
        "source_span": {"paper_id": 8, "page_number": 1},
    },
    9: {
        "claim_text": "Blood pressure increased by 4%.",
        "result_summary": "Blood pressure increased by 4%.",
        "source_span": {"paper_id": 9, "page_number": 1},
    },
}


def _requested_paper_ids(command: list[str]) -> list[int]:
    return [int(command[index + 1]) for index, arg in enumerate(command) if arg == "--paper-id"]


def test_completion_acquires_grounds_promotes_and_reretrieves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already-indexed paper 7 alone is below the adequacy threshold (2), so the
    pmc_oa route still runs and its newly acquired paper 9 is extracted in a
    second bounded batch. Both batches' grounded records are combined for the
    final re-retrieval, matching pre-BT-7 end-to-end behavior."""

    from knowledge_engine_ai.copilot import grounded_completion as module

    commands: list[list[str]] = []
    policy = _policy(tmp_path, min_promoted_records_for_early_stop=2)
    evidence = tmp_path / "evidence.jsonl"
    sources = tmp_path / "sources.csv"
    sources.write_text("title,doi\n", encoding="utf-8")
    plan = _plan(
        _item("existing", disposition="already_indexed", paper_id=7),
        _item("new-pmc", disposition="eligible_full_text", route="pmc_oa"),
    )
    id_counter = {"n": 0}

    def next_id() -> str:
        id_counter["n"] += 1
        return f"ev-{id_counter['n']}"

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
            requested = _requested_paper_ids(command)
            _write_jsonl(
                output,
                [_CLAIMS_BY_PAPER_ID[paper_id] for paper_id in requested],
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
            for record in input_records:
                completed = dict(record)
                completed["schema_version"] = completed.get("schema_version") or "0.1"
                completed["evidence_record_id"] = completed.get("evidence_record_id") or next_id()
                completed["review_status"] = completed.get("review_status") or "draft"
                if completed["evidence_record_id"] not in existing_ids:
                    promoted.append(completed)
            _write_jsonl(output, [*existing, *promoted])
        elif operation == "evidence-review-automate":
            staged = Path(command[command.index("--evidence") + 1])
            assert "--evidence-record-id" not in command
            records = [json.loads(line) for line in staged.read_text().splitlines() if line]
            assert command[command.index("--limit") + 1] == str(len(records))
            for record in records:
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
    assert result.acquisition_skipped_for_adequacy is False
    assert [route.attempted for route in result.acquisition_routes] == [True]
    assert [command[1] for command in commands] == [
        # Batch 1: already-indexed paper 7 alone (1 promoted record) does not
        # meet the configured adequacy threshold of 2, so acquisition proceeds.
        "extraction-review-batch-generate",
        "extraction-review-autoclassify",
        "extraction-review-promote",
        "evidence-review-automate",
        "evidence-record-review-promote",
        "extraction-review-promote",
        "general-question-acquire-pmc",
        # Batch 2: the newly acquired paper 9 is extracted on its own.
        "extraction-review-batch-generate",
        "extraction-review-autoclassify",
        "extraction-review-promote",
        "evidence-review-automate",
        "evidence-record-review-promote",
        "extraction-review-promote",
    ]


def test_completion_skips_acquisition_when_indexed_evidence_is_already_adequate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BT-7 (#92): when the already-indexed papers alone promote enough grounded
    EvidenceRecords to meet the adequacy threshold, every configured acquisition
    route is skipped rather than attempted -- no acquisition subprocess ever runs."""

    from knowledge_engine_ai.copilot import grounded_completion as module

    commands: list[list[str]] = []
    policy = _policy(tmp_path, max_promoted_records=2, min_promoted_records_for_early_stop=2)
    evidence = tmp_path / "evidence.jsonl"
    sources = tmp_path / "sources.csv"
    sources.write_text("title,doi\n", encoding="utf-8")
    plan = _plan(
        _item("existing-1", disposition="already_indexed", paper_id=7),
        _item("existing-2", disposition="already_indexed", paper_id=8),
        _item("new-pmc", disposition="eligible_full_text", route="pmc_oa"),
    )
    id_counter = {"n": 0}

    def next_id() -> str:
        id_counter["n"] += 1
        return f"ev-{id_counter['n']}"

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        commands.append(command)
        operation = command[1]
        if operation == "general-question-acquire-pmc":
            raise AssertionError("acquisition must be skipped once indexed evidence is adequate")
        if operation == "extraction-review-batch-generate":
            output = Path(command[command.index("--output") + 1])
            requested = _requested_paper_ids(command)
            _write_jsonl(output, [_CLAIMS_BY_PAPER_ID[paper_id] for paper_id in requested])
        elif operation == "extraction-review-autoclassify":
            input_path = Path(command[command.index("--input") + 1])
            output = Path(command[command.index("--output") + 1])
            drafts = [json.loads(line) for line in input_path.read_text().splitlines() if line]
            classified = [
                {
                    **draft,
                    "schema_version": None,
                    "evidence_record_id": None,
                    "extraction_method": "m52-evidence-classification-v1",
                    "extraction_status": "draft_review_required",
                    "source_doi": "10.1000/paper",
                    "source_title": "Paper",
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
                for draft in drafts
            ]
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
            for record in input_records:
                completed = dict(record)
                completed["schema_version"] = completed.get("schema_version") or "0.1"
                completed["evidence_record_id"] = completed.get("evidence_record_id") or next_id()
                completed["review_status"] = completed.get("review_status") or "draft"
                if completed["evidence_record_id"] not in existing_ids:
                    promoted.append(completed)
            _write_jsonl(output, [*existing, *promoted])
        elif operation == "evidence-review-automate":
            staged = Path(command[command.index("--evidence") + 1])
            records = [json.loads(line) for line in staged.read_text().splitlines() if line]
            for record in records:
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
    assert result.already_indexed_paper_ids == (7, 8)
    assert result.paper_ids == (7, 8)
    assert result.promoted_record_ids == ("ev-1", "ev-2")
    assert result.acquisition_skipped_for_adequacy is True
    assert result.acquisition_duration_ms == 0
    assert len(result.acquisition_routes) == 1
    skipped_route = result.acquisition_routes[0]
    assert skipped_route.route == "pmc_oa"
    assert skipped_route.attempted is False
    assert skipped_route.skipped_reason is not None
    assert "adequacy" in skipped_route.skipped_reason
    assert result.reretrieval_report is reretrieved
    assert "general-question-acquire-pmc" not in [command[1] for command in commands]


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


def test_extraction_duration_does_not_double_count_the_acquisition_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for a Codex review finding on PR #125: extraction timing
    used to start its clock before the intervening acquisition call and stop it
    after, so `extraction_duration_ms` fully re-included `acquisition_duration_ms`
    whenever already-indexed evidence alone was inadequate and acquisition ran.
    Callers that sum per-stage durations (`bottleneck_report.py`,
    `funnel_report.py`) would then double-count that interval. This drives the
    same already-indexed-then-acquire-then-extract-again path as
    `test_completion_acquires_grounds_promotes_and_reretrieves` above, but with a
    non-pmc route (no internal per-candidate budget polling) and a fake
    monotonic clock advancing by a fixed step on every call, so each phase's
    measured duration is exactly predictable.
    """

    from knowledge_engine_ai.copilot import grounded_completion as module

    policy = _policy(tmp_path, min_promoted_records_for_early_stop=2)
    evidence = tmp_path / "evidence.jsonl"
    sources = tmp_path / "sources.csv"
    sources.write_text("title,doi\n", encoding="utf-8")
    plan = _plan(
        _item("existing", disposition="already_indexed", paper_id=7),
        _item("new-core", disposition="eligible_full_text", route="core"),
    )
    id_counter = {"n": 0}

    def next_id() -> str:
        id_counter["n"] += 1
        return f"ev-{id_counter['n']}"

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        operation = command[1]
        if operation == "general-question-acquire-core":
            request = json.loads(Path(command[2]).read_text(encoding="utf-8"))
            receipt_path = Path(command[command.index("--receipt") + 1])
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "search_run_id": request["search_run_id"],
                        "research_question_id": request["research_question_id"],
                        "acquisition_route": "core",
                        "import_run_id": "import-1",
                        "parsed_count": 1,
                        "persisted_count": 1,
                        "reused_count": 0,
                        "items": [
                            {
                                "candidate_id": "new-core",
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
            requested = _requested_paper_ids(command)
            _write_jsonl(output, [_CLAIMS_BY_PAPER_ID[paper_id] for paper_id in requested])
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
            for record in input_records:
                completed = dict(record)
                completed["schema_version"] = completed.get("schema_version") or "0.1"
                completed["evidence_record_id"] = completed.get("evidence_record_id") or next_id()
                completed["review_status"] = completed.get("review_status") or "draft"
                if completed["evidence_record_id"] not in existing_ids:
                    promoted.append(completed)
            _write_jsonl(output, [*existing, *promoted])
        elif operation == "evidence-review-automate":
            staged = Path(command[command.index("--evidence") + 1])
            records = [json.loads(line) for line in staged.read_text().splitlines() if line]
            for record in records:
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

    # Every `time.monotonic()` call anywhere in `complete_discovered_research`
    # advances by exactly 1.0 simulated second. The non-pmc "core" route makes
    # the call sequence fully deterministic (8 calls total: already-indexed
    # extraction start/stop, acquisition start/stop, acquired-papers extraction
    # start/stop, re-retrieval start/stop), so each phase's duration is
    # predictable to the millisecond.
    clock = iter(float(tick) for tick in range(20))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(module, "_run_ke_command", fake_run)
    monkeypatch.setattr(module, "_resolve_ke_executable", lambda name: name)
    monkeypatch.setattr(
        module, "evidence_report", lambda *args, **kwargs: cast(EvidenceReport, object())
    )

    result = complete_discovered_research(
        "Does Monster Energy raise blood pressure?",
        discovery=_discovery(plan),
        sources=sources,
        evidence=evidence,
        policy=policy,
    )

    assert result.acquisition_duration_ms == 1000
    # Before the fix this was 2000ms extra (the acquisition interval counted a
    # second time): the two extraction batches alone take 1000ms each, summing
    # to 2000ms -- never inflated by `acquisition_duration_ms`.
    assert result.extraction_duration_ms == 2000
    assert result.reretrieval_duration_ms == 1000
