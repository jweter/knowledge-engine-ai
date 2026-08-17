from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine_ai.retrieval_baseline import (
    baseline_payload,
    default_core_corpora,
    git_clean_commit,
    git_commit,
    run_retrieval_baseline,
)
from knowledge_engine_ai.retrieval_benchmark import GoldenQuestion, evaluate_retrieval
from knowledge_engine_ai.retrieval_benchmark_runner import (
    GoldenBenchmarkRun,
    GoldenBenchmarkSuite,
)


def _write_corpus(root: Path, name: str) -> None:
    corpus = root / "data" / "corpora" / name
    corpus.mkdir(parents=True)
    (corpus / "sources.csv").write_text("source_id,title\n", encoding="utf-8")
    (corpus / "evidence_records.jsonl").write_text("", encoding="utf-8")


def test_default_core_corpora_resolves_reviewed_three_domain_layout(tmp_path: Path) -> None:
    _write_corpus(tmp_path, "glp1_weight_loss")
    _write_corpus(tmp_path, "oncology_nsclc_checkpoint_inhibitors")
    _write_corpus(tmp_path, "mental_health_mdd_antidepressants")

    corpora = default_core_corpora(tmp_path)

    assert set(corpora) == {"glp1", "oncology", "mental_health"}
    assert corpora["glp1"].sources == (
        tmp_path / "data" / "corpora" / "glp1_weight_loss" / "sources.csv"
    )


def test_default_core_corpora_fails_when_required_artifact_is_missing(tmp_path: Path) -> None:
    _write_corpus(tmp_path, "glp1_weight_loss")
    _write_corpus(tmp_path, "oncology_nsclc_checkpoint_inhibitors")
    corpus = tmp_path / "data" / "corpora" / "mental_health_mdd_antidepressants"
    corpus.mkdir(parents=True)
    (corpus / "sources.csv").write_text("source_id,title\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="mental_health"):
        default_core_corpora(tmp_path)


def test_baseline_payload_records_repo_provenance_and_measured_ids() -> None:
    question = GoldenQuestion(
        question_id="q1",
        domain="glp1",
        question="Does treatment help?",
        required_evidence_ids=("ev-a", "ev-b"),
        qualifier_evidence_ids=("ev-b",),
    )
    result = evaluate_retrieval(question, ("ev-a", "ev-b"), k=10)
    suite = GoldenBenchmarkSuite(
        limit=10,
        runs=(GoldenBenchmarkRun(question=question, result=result),),
    )

    payload = baseline_payload(suite, core_commit="core123", ai_commit="ai456")

    assert payload["schema_version"] == 1
    assert payload["core_commit"] == "core123"
    assert payload["ai_commit"] == "ai456"
    assert payload["retrieval_limit"] == 10
    assert payload["passes"] is True
    assert payload["runs"][0]["result"]["retrieved_evidence_ids"] == ("ev-a", "ev-b")


def test_baseline_payload_rejects_blank_commit_provenance() -> None:
    suite = GoldenBenchmarkSuite(limit=10, runs=())

    with pytest.raises(ValueError, match="Core commit"):
        baseline_payload(suite, core_commit=" ", ai_commit="ai456")
    with pytest.raises(ValueError, match="AI commit"):
        baseline_payload(suite, core_commit="core123", ai_commit="")


def test_git_commit_uses_checkout_root_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "abc123\n"

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        captured["command"] = command
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr("knowledge_engine_ai.retrieval_baseline.subprocess.run", fake_run)

    assert git_commit(tmp_path) == "abc123"
    assert captured["command"] == ["git", "-C", str(tmp_path), "rev-parse", "HEAD"]
    assert captured.get("shell", False) is False


def test_git_clean_commit_rejects_tracked_changes_before_resolving_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = " M data/corpora/glp1_weight_loss/evidence_records.jsonl\n"

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        calls.append(command)
        return Completed()

    monkeypatch.setattr("knowledge_engine_ai.retrieval_baseline.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="tracked files"):
        git_clean_commit(tmp_path)

    assert calls == [
        ["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=no"]
    ]


def test_git_clean_commit_allows_clean_tracked_state_and_ignores_untracked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    class Completed:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        calls.append(command)
        if "status" in command:
            return Completed("")
        return Completed("abc123\n")

    monkeypatch.setattr("knowledge_engine_ai.retrieval_baseline.subprocess.run", fake_run)

    assert git_clean_commit(tmp_path) == "abc123"
    assert calls == [
        ["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=no"],
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
    ]


def test_run_retrieval_baseline_binds_questions_corpora_and_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "glp1_weight_loss",
        "oncology_nsclc_checkpoint_inhibitors",
        "mental_health_mdd_antidepressants",
    ):
        _write_corpus(tmp_path, name)

    question = GoldenQuestion(
        question_id="q1",
        domain="glp1",
        question="Does treatment help?",
        required_evidence_ids=("ev-a",),
    )
    result = evaluate_retrieval(question, ("ev-a",), k=7)
    suite = GoldenBenchmarkSuite(
        limit=7,
        runs=(GoldenBenchmarkRun(question=question, result=result),),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "knowledge_engine_ai.retrieval_baseline.default_golden_questions",
        lambda: (question,),
    )

    def fake_run(*args: object, **kwargs: object) -> GoldenBenchmarkSuite:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return suite

    monkeypatch.setattr(
        "knowledge_engine_ai.retrieval_baseline.run_golden_benchmark",
        fake_run,
    )
    monkeypatch.setattr(
        "knowledge_engine_ai.retrieval_baseline.git_clean_commit",
        lambda root: "core123" if root == tmp_path else "ai456",
    )
    ai_root = tmp_path / "ai"

    payload = run_retrieval_baseline(
        core_root=tmp_path,
        ai_root=ai_root,
        limit=7,
        ke_executable="ke-test",
    )

    assert payload["core_commit"] == "core123"
    assert payload["ai_commit"] == "ai456"
    assert payload["retrieval_limit"] == 7
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["core_root"] == tmp_path
    assert kwargs["ke_executable"] == "ke-test"
