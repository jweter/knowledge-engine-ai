"""CLI for repeatable cold/warm General Question Research Loop benchmarks."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from knowledge_engine_ai.copilot.discovery_policy import FederatedDiscoveryPolicy
from knowledge_engine_ai.copilot.grounded_completion import GroundedCompletionPolicy
from knowledge_engine_ai.copilot.run_research_question import run_research_question
from knowledge_engine_ai.llm import DEFAULT_OLLAMA_HOST, OllamaLLM
from knowledge_engine_ai.research_pipeline_benchmark import (
    compute_evidence_store_revision,
    execute_research_benchmark,
)
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection

app = typer.Typer(add_completion=False)

QuestionArgument = Annotated[str, typer.Argument(help="Natural-language research question.")]
SourcesOption = Annotated[
    Path,
    typer.Option("--sources", exists=True, dir_okay=False, help="Core sources.csv path."),
]
EvidenceOption = Annotated[
    Path,
    typer.Option("--evidence", exists=True, dir_okay=False, help="Writable EvidenceRecord JSONL."),
]
SessionDbOption = Annotated[
    Path,
    typer.Option("--session-db", help="SQLite path for durable benchmark ResearchSessions."),
]
LedgerRootOption = Annotated[
    Path,
    typer.Option("--ledger-root", help="Core federated-discovery ledger directory."),
]
PapersDirOption = Annotated[
    Path,
    typer.Option("--papers-dir", help="Directory for bounded acquired research papers."),
]
ModelOption = Annotated[
    str | None,
    typer.Option("--llm-model", help="Ollama model used for grounding and synthesis."),
]
OllamaHostOption = Annotated[
    str | None,
    typer.Option("--ollama-host", help="Ollama HTTP endpoint."),
]
KeExecutableOption = Annotated[
    str,
    typer.Option("--ke-executable", help="Core `ke` executable or absolute path."),
]
ProvidersOption = Annotated[
    str | None,
    typer.Option(
        "--providers",
        help="Optional comma-separated provider subset, e.g. pubmed,semantic_scholar.",
    ),
]
RepeatsOption = Annotated[
    int,
    typer.Option("--repeats", min=1, max=10, help="Run count; 2 measures cold then reuse."),
]
TimeoutOption = Annotated[
    float,
    typer.Option("--timeout-seconds", min=1.0, help="Shared wall-clock budget per research run."),
]
ScenarioOption = Annotated[
    str,
    typer.Option("--scenario-id", help="Stable benchmark scenario label."),
]
OutputOption = Annotated[
    Path | None,
    typer.Option("--output", help="Optional JSON output path; stdout when omitted."),
]


@app.command()
def run(
    question: QuestionArgument,
    sources: SourcesOption,
    evidence: EvidenceOption,
    session_db: SessionDbOption,
    ledger_root: LedgerRootOption,
    papers_dir: PapersDirOption,
    llm_model: ModelOption = None,
    ollama_host: OllamaHostOption = None,
    ke_executable: KeExecutableOption = "ke",
    providers: ProvidersOption = None,
    repeats: RepeatsOption = 2,
    timeout_seconds: TimeoutOption = 180.0,
    scenario_id: ScenarioOption = "ad-hoc-research-question",
    output: OutputOption = None,
) -> None:
    """Execute the same question cold then warm and emit one benchmark JSON document."""

    model = llm_model or os.environ.get("KE_AI_LLM_MODEL")
    if model is None or not model.strip():
        raise typer.BadParameter("--llm-model or KE_AI_LLM_MODEL is required.")
    host = ollama_host or os.environ.get("KE_AI_OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
    provider_tuple = _parse_providers(providers)

    ledger_root.mkdir(parents=True, exist_ok=True)
    papers_dir.mkdir(parents=True, exist_ok=True)
    session_db.parent.mkdir(parents=True, exist_ok=True)

    repository = SessionRepository(new_connection(str(session_db)))
    llm = OllamaLLM(model=model.strip(), host=host)
    discovery_policy = FederatedDiscoveryPolicy(
        ledger_root=ledger_root,
        discovery_providers=provider_tuple,
        enable_acquisition_plan=True,
        ke_executable=ke_executable,
    )
    completion_policy = GroundedCompletionPolicy(
        ledger_root=ledger_root,
        papers_dir=papers_dir,
        grounding_model=model.strip(),
    )

    def run_once(run_question: str):  # type: ignore[no-untyped-def]
        return run_research_question(
            run_question,
            session_repository=repository,
            sources=sources,
            evidence=evidence,
            llm=llm,
            discovery_policy=discovery_policy,
            grounded_completion_policy=completion_policy,
            ke_executable=ke_executable,
            timeout_seconds=timeout_seconds,
        )

    suite = execute_research_benchmark(
        question,
        scenario_id=scenario_id,
        run_once=run_once,
        repeats=repeats,
        evidence_store_revision=lambda: compute_evidence_store_revision(evidence),
    )
    payload = suite.to_json()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        typer.echo(str(output))
        return
    sys.stdout.write(payload)


def _parse_providers(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    providers = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    if not providers:
        raise typer.BadParameter("--providers must contain at least one provider name.")
    return providers


if __name__ == "__main__":
    app()
