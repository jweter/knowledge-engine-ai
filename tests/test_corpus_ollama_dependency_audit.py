"""Characterize current corpus and model prerequisites before online-only migration.

These tests intentionally pin today's restrictions. The next roadmap slice
must update them when it supplies a safe alternative path.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from knowledge_engine_ai.cli import app
from knowledge_engine_ai.copilot.run_research_question import run_research_question
from knowledge_engine_ai.ke_client import evidence_report
from knowledge_engine_ai.orchestrator.workflow import run_fixed_evidence_workflow


@pytest.mark.parametrize("command", ["ask", "research"])
def test_existing_cli_requires_corpus_paths(command: str, tmp_path: Path) -> None:
    missing_sources = CliRunner().invoke(app, [command, "a research question"])
    assert missing_sources.exit_code != 0
    assert "--sources" in missing_sources.output

    sources = tmp_path / "sources.csv"
    sources.write_text("", encoding="utf-8")
    missing_evidence = CliRunner().invoke(
        app, [command, "a research question", "--sources", str(sources)]
    )
    assert missing_evidence.exit_code != 0
    assert "--evidence" in missing_evidence.output


def test_research_cli_requires_model_even_with_local_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KE_AI_LLM_MODEL", raising=False)
    sources = tmp_path / "sources.csv"
    evidence = tmp_path / "evidence.jsonl"
    sources.write_text("", encoding="utf-8")
    evidence.write_text("", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["research", "a research question", "--sources", str(sources), "--evidence", str(evidence)],
    )
    assert result.exit_code != 0
    assert "research requires --llm-model or KE_AI_LLM_MODEL" in " ".join(result.output.split())


@pytest.mark.parametrize(
    ("function", "required"),
    [
        (evidence_report, ("sources", "evidence")),
        (run_fixed_evidence_workflow, ("sources", "evidence")),
        (run_research_question, ("sources", "evidence", "llm")),
    ],
)
def test_existing_orchestration_requires_local_inputs(
    function: Callable[..., object], required: tuple[str, ...]
) -> None:
    parameters = inspect.signature(function).parameters
    for name in required:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty
