"""`ke-ai` -- Knowledge Engine AI's CLI. Retrieval Intelligence, first slice.

No synthesis, no confidence scoring, no LLM call. Every line printed
traces back to a real `ke evidence-report` field -- see `docs/ai_design.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from knowledge_engine_ai.ke_client import KeCommandError, evidence_report
from knowledge_engine_ai.models import EvidenceReport

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


@app.command()
def ask(
    question: QuestionArgument,
    sources: SourcesOption,
    evidence: EvidenceOption,
    limit: LimitOption = 5,
) -> None:
    """Retrieve ranked, source-linked evidence for a research question.

    Retrieval only -- runs `ke evidence-report --format json` and prints
    a compact summary of the real, structured result. No synthesis is
    performed and no confidence rating is computed.
    """

    try:
        report = evidence_report(question, sources=sources, evidence=evidence, limit=limit)
    except KeCommandError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    _print_report(report)


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
        console.print()

    console.print(f"[dim]{report.disclaimer}[/dim]")
