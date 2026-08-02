"""`ke-ai` -- Knowledge Engine AI's CLI. Retrieval + Evidence Intelligence.

No LLM call, no synthesis across claims. Every line printed traces back
to a real `ke evidence-report`/`ke evidence-intelligence` field -- see
`docs/ai_design.md`.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from knowledge_engine_ai.ke_client import KeCommandError, enriched_evidence_report
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
FormatOption = Annotated[
    str,
    typer.Option("--format", help="Output format: 'text' (default) or 'json'."),
]


@app.command()
def ask(
    question: QuestionArgument,
    sources: SourcesOption,
    evidence: EvidenceOption,
    limit: LimitOption = 5,
    output_format: FormatOption = "text",
) -> None:
    """Retrieve ranked, source-linked evidence for a research question.

    Runs `ke evidence-report --format json`, then attaches each matched
    evidence record's Evidence Intelligence (`ke evidence-intelligence
    --format json`) where the record already has a graph claim. Retrieval
    plus already-computed, already-stored signals only -- no cross-claim
    synthesis, no new confidence judgment, no LLM call. `--format json`
    is the structured, machine-readable sibling of the default text
    summary, for a consumer (e.g. `knowledge-engine-web`) that needs to
    parse results programmatically rather than scrape text.
    """

    if output_format not in ("text", "json"):
        raise typer.BadParameter("--format must be 'text' or 'json'.")

    try:
        report = enriched_evidence_report(question, sources=sources, evidence=evidence, limit=limit)
    except KeCommandError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_format == "json":
        # Avoid Rich's word-wrapping corrupting JSON output with inserted
        # newlines, matching `ke evidence-report --format json`'s same fix.
        sys.stdout.write(json.dumps(dataclasses.asdict(report), indent=2, sort_keys=True) + "\n")
        return

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
