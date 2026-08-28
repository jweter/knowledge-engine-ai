from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine_ai.copilot.discovery_policy import DiscoveryAugmentationResult
from knowledge_engine_ai.copilot.grounded_completion import (
    GroundedCompletionPolicy,
    complete_discovered_research,
)
from knowledge_engine_ai.execution import ExecutionBudget
from knowledge_engine_ai.ke_client import (
    GeneralQuestionAcquisitionIdentity,
    GeneralQuestionAcquisitionItem,
    GeneralQuestionAcquisitionPlanResult,
)


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _item(candidate_id: str, *, route: str = "pmc_oa") -> GeneralQuestionAcquisitionItem:
    return GeneralQuestionAcquisitionItem(
        candidate_id=candidate_id,
        title=f"Paper {candidate_id}",
        disposition="eligible_full_text",
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
        full_text_url="https://example.invalid/paper.pdf",
        xml_url=None,
        license="CC BY",
        open_access=True,
        existing_paper_id=None,
        reason=None,
    )


def _plan(*items: GeneralQuestionAcquisitionItem) -> GeneralQuestionAcquisitionPlanResult:
    return GeneralQuestionAcquisitionPlanResult(
        schema_version=1,
        search_run_id="run-live",
        research_question_id="rq-live",
        query_text="music exercise endurance",
        requested_candidate_count=len(items),
        resolved_candidate_count=len(items),
        already_indexed_count=0,
        full_text_selected_count=len(items),
        metadata_only_count=0,
        skipped_budget_count=0,
        missing_candidate_count=0,
        provider_failures=(),
        items=tuple(items),
    )


def _discovery(plan: GeneralQuestionAcquisitionPlanResult) -> DiscoveryAugmentationResult:
    return DiscoveryAugmentationResult(
        triggered=True,
        trigger_reason="coverage gap",
        evidence_record_coverage=0,
        acquisition_plan=plan,
        acquisition_plan_attempted=True,
    )


def _policy(tmp_path: Path, *, max_full_text: int = 5) -> GroundedCompletionPolicy:
    return GroundedCompletionPolicy(
        ledger_root=tmp_path / "ledger",
        papers_dir=tmp_path / "papers",
        grounding_model="test-grounder",
        core_working_directory=tmp_path / "core",
        max_candidates_per_route=10,
        max_full_text_acquisitions_per_route=max_full_text,
        max_elapsed_seconds_per_route=30,
    )


def _write_receipt(command: list[str], candidate_id: str, paper_id: int) -> None:
    request = json.loads(Path(command[2]).read_text(encoding="utf-8"))
    receipt_path = Path(command[command.index("--receipt") + 1])
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "search_run_id": request["search_run_id"],
                "research_question_id": request["research_question_id"],
                "acquisition_route": "pmc_oa",
                "import_run_id": f"import-{candidate_id}",
                "parsed_count": 1,
                "persisted_count": 1,
                "reused_count": 0,
                "items": [
                    {
                        "candidate_id": candidate_id,
                        "paper_id": paper_id,
                        "persistence_status": "persisted",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_one_invalid_pmc_candidate_does_not_discard_valid_neighbors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine_ai.copilot import grounded_completion as module

    requests: list[dict[str, object]] = []
    route_deadlines: list[float] = []
    extracted: list[tuple[int, ...]] = []
    paper_ids = {"pmc-good-1": 101, "pmc-good-2": 103}

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        assert command[1] == "general-question-acquire-pmc"
        request = json.loads(Path(command[2]).read_text(encoding="utf-8"))
        requests.append(request)
        budget = kwargs["execution_budget"]
        assert isinstance(budget, ExecutionBudget)
        route_deadlines.append(budget.deadline_monotonic)
        candidate_id = str(request["candidate_ids"][0])
        if candidate_id == "pmc-bad":
            return _Completed(
                returncode=1,
                stderr="A planned PMC candidate lacks verified reusable full-text evidence.",
            )
        _write_receipt(command, candidate_id, paper_ids[candidate_id])
        return _Completed()

    def fake_extract(papers: tuple[int, ...], **kwargs: object) -> object:
        extracted.append(papers)
        return module._ExtractionResult(0, 0, (), (), ())

    monkeypatch.setattr(module, "_run_ke_command", fake_run)
    monkeypatch.setattr(module, "_resolve_ke_executable", lambda name: name)
    monkeypatch.setattr(module, "_extract_ground_promote", fake_extract)

    result = complete_discovered_research(
        "Does music improve exercise endurance?",
        discovery=_discovery(
            _plan(
                _item("pmc-good-1"),
                _item("pmc-bad"),
                _item("pmc-good-2"),
            )
        ),
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        policy=_policy(tmp_path),
    )

    assert [request["candidate_ids"] for request in requests] == [
        ["pmc-good-1"],
        ["pmc-bad"],
        ["pmc-good-2"],
    ]
    assert all(request["max_candidates"] == 1 for request in requests)
    assert all(request["max_full_text_acquisitions"] == 1 for request in requests)
    assert len(set(route_deadlines)) == 1
    assert result.paper_ids == (101, 103)
    assert extracted == [(101, 103)]
    assert len(result.acquisition_routes) == 3
    assert sum(route.persisted_count for route in result.acquisition_routes) == 2
    failed = [route for route in result.acquisition_routes if route.error is not None]
    assert len(failed) == 1
    assert failed[0].candidate_ids == ("pmc-bad",)
    assert "verified reusable full-text evidence" in str(failed[0].error)


def test_pmc_isolation_respects_route_full_text_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine_ai.copilot import grounded_completion as module

    attempted: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        request = json.loads(Path(command[2]).read_text(encoding="utf-8"))
        candidate_id = str(request["candidate_ids"][0])
        attempted.append(candidate_id)
        _write_receipt(command, candidate_id, 200 + len(attempted))
        return _Completed()

    monkeypatch.setattr(module, "_run_ke_command", fake_run)
    monkeypatch.setattr(module, "_resolve_ke_executable", lambda name: name)
    monkeypatch.setattr(
        module,
        "_extract_ground_promote",
        lambda *args, **kwargs: module._ExtractionResult(0, 0, (), (), ()),
    )

    result = complete_discovered_research(
        "Question?",
        discovery=_discovery(_plan(_item("one"), _item("two"), _item("three"))),
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        policy=_policy(tmp_path, max_full_text=2),
    )

    assert attempted == ["one", "two"]
    assert result.paper_ids == (201, 202)
    assert [route.candidate_ids for route in result.acquisition_routes] == [("one",), ("two",)]


def test_non_pmc_route_keeps_batched_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine_ai.copilot import grounded_completion as module

    requests: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> _Completed:
        assert command[1] == "general-question-acquire-core"
        request = json.loads(Path(command[2]).read_text(encoding="utf-8"))
        requests.append(request)
        receipt_path = Path(command[command.index("--receipt") + 1])
        receipt_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "search_run_id": request["search_run_id"],
                    "research_question_id": request["research_question_id"],
                    "acquisition_route": "core",
                    "import_run_id": "import-core",
                    "parsed_count": 2,
                    "persisted_count": 2,
                    "reused_count": 0,
                    "items": [
                        {"candidate_id": candidate_id, "paper_id": 300 + index}
                        for index, candidate_id in enumerate(request["candidate_ids"], start=1)
                    ],
                }
            ),
            encoding="utf-8",
        )
        return _Completed()

    monkeypatch.setattr(module, "_run_ke_command", fake_run)
    monkeypatch.setattr(module, "_resolve_ke_executable", lambda name: name)
    monkeypatch.setattr(
        module,
        "_extract_ground_promote",
        lambda *args, **kwargs: module._ExtractionResult(0, 0, (), (), ()),
    )

    result = complete_discovered_research(
        "Question?",
        discovery=_discovery(_plan(_item("core-a", route="core"), _item("core-b", route="core"))),
        sources=tmp_path / "sources.csv",
        evidence=tmp_path / "evidence.jsonl",
        policy=_policy(tmp_path),
    )

    assert len(requests) == 1
    assert requests[0]["candidate_ids"] == ["core-a", "core-b"]
    assert len(result.acquisition_routes) == 1
    assert result.acquisition_routes[0].candidate_ids == ("core-a", "core-b")
    assert result.paper_ids == (301, 302)
