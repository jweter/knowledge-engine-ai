"""`ke-ai` -- Knowledge Engine AI's CLI. Retrieval + Evidence Intelligence.

Every retrieval and Evidence Intelligence line printed traces back to a
real `ke evidence-report`/`ke evidence-intelligence` field. `--synthesize`
is the one opt-in exception: a local, offline LLM narrates that same
already-computed evidence into a paragraph -- see `docs/ai_design.md`'s
"Decision: local LLM" section and `knowledge_engine_ai/synthesis.py`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from knowledge_engine_ai.ke_client import KeCommandError, enriched_evidence_report
from knowledge_engine_ai.llm import DEFAULT_OLLAMA_HOST, LocalLLMError, OllamaLLM
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.synthesis import synthesize_answer

app = typer.Typer(add_completion=False)
console = Console()


# Without this empty callback, Typer collapses a single-command app so
# `ask` gets swallowed as the QUESTION argument instead of staying a
# subcommand name. Keep it once a second command is added.
@app.callback()
def _callback() -> None:
    pass


QuestionArgument = Annotated[str, typer.Argument(help="Natural-language research question.")]
SourcesOption = Annotated[
    Path,
    typer.Option("--sources", help="Corpus sources.csv metadata overlay.", exists=True),
]
EvidenceOption = Annotated[
    Path,
    typer.Option("--evidence", help="Evidence records JSONL file.", exists=True),
]
LimitOption = Annotated[int, typer.Option("--limit", "-n", min=1, max=100)]
FormatOption = Annotated[
    str,
    typer.Option("--format", help="Output format: 'text' (default) or 'json'."),
]
SynthesizeOption = Annotated[
    bool,
    typer.Option(
        "--synthesize",
        help=(
            "Have a local, offline LLM (served by Ollama) narrate the retrieved evidence into "
            "one grounded paragraph, citing each evidence_record_id. Requires --llm-model or "
            "KE_AI_LLM_MODEL. Off by default: real inference, not free."
        ),
    ),
]
LlmModelOption = Annotated[
    str | None,
    typer.Option(
        "--llm-model",
        help=(
            "Ollama model name for --synthesize, e.g. 'qwen2.5:1.5b' or 'qwen3:8b' "
            "(must already be pulled: `ollama pull <name>`). Falls back to KE_AI_LLM_MODEL "
            "if not given."
        ),
    ),
]
OllamaHostOption = Annotated[
    str | None,
    typer.Option(
        "--ollama-host",
        help=f"Ollama server URL. Falls back to KE_AI_OLLAMA_HOST, then {DEFAULT_OLLAMA_HOST}.",
    ),
]


@app.command()
def ask(
    question: QuestionArgument,
    sources: SourcesOption,
    evidence: EvidenceOption,
    limit: LimitOption = 5,
    output_format: FormatOption = "text",
    synthesize: SynthesizeOption = False,
    llm_model: LlmModelOption = None,
    ollama_host: OllamaHostOption = None,
) -> None:
    """Retrieve ranked, source-linked evidence for a research question.

    Runs `ke evidence-report --format json`, then attaches each matched
    evidence record's Evidence Intelligence (`ke evidence-intelligence
    --format json`) where the record already has a graph claim. Retrieval
    plus already-computed, already-stored signals only -- no cross-claim
    synthesis, no new confidence judgment, unless `--synthesize` is
    passed. `--format json` is the structured, machine-readable sibling
    of the default text summary, for a consumer (e.g.
    `knowledge-engine-web`) that needs to parse results programmatically
    rather than scrape text.
    """

    if output_format not in ("text", "json"):
        raise typer.BadParameter("--format must be 'text' or 'json'.")

    try:
        report = enriched_evidence_report(question, sources=sources, evidence=evidence, limit=limit)
    except KeCommandError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    synthesis: str | None = None
    if synthesize:
        model = llm_model or os.environ.get("KE_AI_LLM_MODEL")
        if model is None:
            console.print("[red]Error:[/red] --synthesize requires --llm-model or KE_AI_LLM_MODEL.")
            raise typer.Exit(1)
        host = ollama_host or os.environ.get("KE_AI_OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
        try:
            llm = OllamaLLM(model=model, host=host)
            synthesis = synthesize_answer(report, llm)
        except LocalLLMError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc

    if output_format == "json":
        payload = dataclasses.asdict(report)
        if synthesize:
            payload["synthesis"] = synthesis
        # Avoid Rich's word-wrapping corrupting JSON output with inserted
        # newlines, matching `ke evidence-report --format json`'s same fix.
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return

    _print_report(report)
    if synthesize:
        console.print()
        console.print("[bold]AI-generated synthesis[/bold] (local model, not a new judgment call):")
        if synthesis is None:
            console.print(
                "[yellow]No evidence with a stated claim was retrieved to narrate.[/yellow]"
            )
        else:
            # `synthesis` is model-generated text that may contain literal
            # "[...]" citations -- escape it so Rich renders those brackets
            # verbatim instead of treating them as markup tags.
            console.print(escape(synthesis))


def _print_report(report: EvidenceReport) -> None:
    console.print(f"[bold]Question:[/bold] {report.question}")
    summary = report.evidence_summary
    console.print(
        f"[bold]Evidence summary:[/bold] {summary.total} records "
        f"({summary.draft} draft, {summary.reviewed} reviewed) -- {summary.readiness_note}"
    )
    console.print()

    if not report.papers:
        console.print("[yellow]No relevant papers found.[/yellow]")
        return

    for paper in report.papers:
        console.print(f"[bold]{paper.rank}. {paper.title}[/bold]")
        console.print(f"   DOI: {paper.doi} -- {paper.year}")
        console.print(f"   Matched: {paper.why_matched}")
        console.print(f"   Evidence records: {len(paper.evidence_records)}")
        for record in paper.evidence_records:
            if record.claim_text:
                console.print(f"     - {record.claim_text}")
            intelligence = record.evidence_intelligence
            if intelligence is not None:
                consensus_score = intelligence.evidence_consensus.score
                confidence_score = intelligence.claim_confidence.score
                consensus_text = (
                    str(consensus_score) if consensus_score is not None else "not yet assessable"
                )
                confidence_text = (
                    str(confidence_score) if confidence_score is not None else "not yet assessable"
                )
                console.print(
                    f"       Evidence Quality: {intelligence.evidence_quality.score}/100 -- "
                    f"Evidence Consensus: {consensus_text} "
                    f"({intelligence.evidence_consensus.reliability}) -- "
                    f"Claim Confidence: {confidence_text} "
                    f"({intelligence.claim_confidence.reliability})"
                )
        console.print()

    console.print(f"[dim]{report.disclaimer}[/dim]")
