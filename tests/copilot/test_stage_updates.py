from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine_ai.copilot import grounded_completion as gc
from knowledge_engine_ai.copilot.grounded_completion import (
    AcquisitionRouteResult,
    complete_discovered_research,
)
from knowledge_engine_ai.copilot.progress_report import ResearchProgressStage
from knowledge_engine_ai.copilot.run_research_question import run_research_question
from knowledge_engine_ai.copilot.stage_updates import (
    RESEARCH_STAGE_UPDATE_SCHEMA_VERSION,
    ResearchStageNotifier,
    ResearchStageUpdate,
)
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection
from tests.copilot.test_grounded_completion import _discovery, _item, _plan, _policy
from tests.copilot.test_run_research_question import (
    _GROUNDED_RECORD,
    _fake_run,
    _FakeLLM,
    _payload,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_hook_stage_names_match_the_progress_contract() -> None:
    assert ResearchProgressStage.ACQUIRING_SOURCES.value == gc.STAGE_ACQUIRING_SOURCES
    assert (
        ResearchProgressStage.VALIDATING_EXTRACTING_EVIDENCE.value
        == gc.STAGE_VALIDATING_EXTRACTING_EVIDENCE
    )
    assert ResearchProgressStage.RERETRIEVING.value == gc.STAGE_RERETRIEVING


def test_notifier_records_ordered_updates_with_elapsed_time() -> None:
    clock = _Clock()
    seen: list[ResearchStageUpdate] = []
    notifier = ResearchStageNotifier("s-1", seen.append, clock=clock)
    notifier.notify(ResearchProgressStage.SEARCHING_INDEXED_EVIDENCE)
    clock.now += 1.5
    notifier.notify("discovering_sources", "detail")

    assert [u.sequence for u in notifier.updates] == [1, 2]
    assert [u.stage for u in notifier.updates] == [
        ResearchProgressStage.SEARCHING_INDEXED_EVIDENCE,
        ResearchProgressStage.DISCOVERING_SOURCES,
    ]
    assert [u.elapsed_ms for u in notifier.updates] == [0, 1500]
    assert seen == list(notifier.updates)
    assert all(u.session_id == "s-1" for u in seen)
    assert all(u.schema_version == RESEARCH_STAGE_UPDATE_SCHEMA_VERSION for u in seen)
    assert seen[1].to_dict() == {
        "schema_version": 1,
        "sequence": 2,
        "session_id": "s-1",
        "stage": "discovering_sources",
        "elapsed_ms": 1500,
        "detail": "detail",
    }


def test_notifier_without_callback_still_records() -> None:
    notifier = ResearchStageNotifier("s-1")
    notifier.notify(ResearchProgressStage.RERETRIEVING)
    assert [u.stage for u in notifier.updates] == [ResearchProgressStage.RERETRIEVING]
    assert notifier.callback_error_count == 0


def test_failing_callback_is_swallowed_and_counted() -> None:
    def broken(_update: ResearchStageUpdate) -> None:
        raise RuntimeError("observer exploded")

    notifier = ResearchStageNotifier("s-1", broken)
    notifier.notify(ResearchProgressStage.SEARCHING_INDEXED_EVIDENCE)
    notifier.notify(ResearchProgressStage.DISCOVERING_SOURCES)
    assert notifier.callback_error_count == 2
    assert len(notifier.updates) == 2  # still recorded for the result


def test_unknown_stage_is_ignored_not_raised() -> None:
    notifier = ResearchStageNotifier("s-1")
    notifier.notify("not_a_stage")
    assert notifier.updates == ()
    assert notifier.callback_error_count == 1


def test_negative_clock_skew_never_yields_negative_elapsed() -> None:
    clock = _Clock()
    notifier = ResearchStageNotifier("s-1", clock=clock)
    clock.now -= 5
    notifier.notify(ResearchProgressStage.SEARCHING_INDEXED_EVIDENCE)
    assert notifier.updates[0].elapsed_ms == 0


def _extraction(*record_ids: str) -> gc._ExtractionResult:
    count = len(record_ids)
    return gc._ExtractionResult(count, count, record_ids, record_ids, record_ids)


def _complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plan, policy, hook, **fakes):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gc, "_extract_ground_promote", fakes["extract"])
    monkeypatch.setattr(gc, "_execute_acquisition_route_attempts", fakes["acquire"])
    monkeypatch.setattr(gc, "evidence_report", fakes["report"])
    return complete_discovered_research(
        "q",
        discovery=_discovery(plan),
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        policy=policy,
        on_stage=hook,
    )


def test_completion_announces_each_stage_that_actually_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(
        _item("existing", disposition="already_indexed", paper_id=7),
        _item("new-pmc", disposition="eligible_full_text", route="pmc_oa"),
    )
    calls: list[tuple[str, str]] = []
    extractions = iter([_extraction("ev-1"), _extraction("ev-2")])

    result = _complete(
        tmp_path,
        monkeypatch,
        plan,
        _policy(tmp_path, min_promoted_records_for_early_stop=2),
        lambda stage, detail: calls.append((stage, detail)),
        extract=lambda *a, **k: next(extractions),
        acquire=lambda *a, **k: [
            AcquisitionRouteResult(
                route="pmc_oa", candidate_ids=("new-pmc",), attempted=True, paper_ids=(9,)
            )
        ],
        report=lambda *a, **k: None,
    )

    assert [stage for stage, _ in calls] == [
        "validating_extracting_evidence",
        "acquiring_sources",
        "validating_extracting_evidence",
        "reretrieving",
    ]
    assert result.acquisition_skipped_for_adequacy is False


def test_completion_does_not_announce_acquisition_when_skipped_for_adequacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(
        _item("a", disposition="already_indexed", paper_id=7),
        _item("b", disposition="already_indexed", paper_id=8),
        _item("new-pmc", disposition="eligible_full_text", route="pmc_oa"),
    )
    calls: list[str] = []

    def never_acquire(*_a: object, **_k: object) -> list[AcquisitionRouteResult]:
        raise AssertionError("acquisition must be skipped")

    result = _complete(
        tmp_path,
        monkeypatch,
        plan,
        _policy(tmp_path, min_promoted_records_for_early_stop=2),
        lambda stage, _detail: calls.append(stage),
        extract=lambda *a, **k: _extraction("ev-1", "ev-2"),
        acquire=never_acquire,
        report=lambda *a, **k: None,
    )

    assert calls == ["validating_extracting_evidence", "reretrieving"]
    assert "acquiring_sources" not in calls
    assert result.acquisition_skipped_for_adequacy is True


def test_completion_does_not_announce_reretrieval_without_promoted_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(_item("a", disposition="already_indexed", paper_id=7))
    calls: list[str] = []

    _complete(
        tmp_path,
        monkeypatch,
        plan,
        _policy(tmp_path),
        lambda stage, _detail: calls.append(stage),
        extract=lambda *a, **k: _extraction(),
        acquire=lambda *a, **k: [],
        report=lambda *a, **k: None,
    )

    assert calls == ["validating_extracting_evidence"]


def test_failing_stage_hook_does_not_change_the_completion_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(
        _item("a", disposition="already_indexed", paper_id=7),
        _item("b", disposition="already_indexed", paper_id=8),
    )

    policy = _policy(tmp_path, min_promoted_records_for_early_stop=2)

    def run(hook):  # type: ignore[no-untyped-def]
        return _complete(
            tmp_path,
            monkeypatch,
            plan,
            policy,
            hook,
            extract=lambda *a, **k: _extraction("ev-1", "ev-2"),
            acquire=lambda *a, **k: [],
            report=lambda *a, **k: None,
        )

    def broken(_stage: str, _detail: str) -> None:
        raise RuntimeError("boom")

    def outcome(result):  # type: ignore[no-untyped-def]
        return (
            result.promoted_record_ids,
            result.paper_ids,
            result.acquisition_skipped_for_adequacy,
            result.extraction_error,
            result.skipped_reason,
        )

    assert outcome(run(broken)) == outcome(run(None))


def test_run_research_question_announces_stages_and_returns_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    seen: list[ResearchStageUpdate] = []

    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=SessionRepository(new_connection(":memory:")),
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
        on_stage=seen.append,
    )

    assert [u.stage for u in seen] == [
        ResearchProgressStage.SEARCHING_INDEXED_EVIDENCE,
        result.progress_report.progress_stage,  # type: ignore[union-attr]
    ]
    assert result.stage_updates == tuple(seen)
    assert all(u.session_id == result.session_id for u in seen)
    assert [u.sequence for u in seen] == [1, 2]
    assert seen[-1].detail == ("final" if result.progress_report.final else "")  # type: ignore[union-attr]
    json.dumps([u.to_dict() for u in seen])  # JSON-serializable for Web


def test_run_research_question_ignores_a_failing_observer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))

    def broken(_update: ResearchStageUpdate) -> None:
        raise RuntimeError("observer exploded")

    def run(callback):  # type: ignore[no-untyped-def]
        return run_research_question(
            "does semaglutide reduce body weight",
            session_repository=SessionRepository(new_connection(":memory:")),
            sources=tmp_path / "s.csv",
            evidence=tmp_path / "e.jsonl",
            llm=_FakeLLM(),
            session_id="fixed-id",
            on_stage=callback,
        )

    with_broken = run(broken)
    without = run(None)
    assert with_broken.narrative == without.narrative
    assert with_broken.close_result.status == without.close_result.status
    assert with_broken.progress_report is not None and without.progress_report is not None
    assert with_broken.progress_report.progress_stage == without.progress_report.progress_stage
    assert with_broken.progress_report.final == without.progress_report.final
    assert [u.stage for u in with_broken.stage_updates] == [u.stage for u in without.stage_updates]


def test_omitting_on_stage_keeps_prior_result_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(_payload(evidence_records=[_GROUNDED_RECORD])))
    result = run_research_question(
        "does semaglutide reduce body weight",
        session_repository=SessionRepository(new_connection(":memory:")),
        sources=tmp_path / "s.csv",
        evidence=tmp_path / "e.jsonl",
        llm=_FakeLLM(),
    )
    assert result.progress_report is not None
    assert len(result.stage_updates) >= 2
