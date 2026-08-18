"""`ke-ai` -- Knowledge Engine AI's CLI. Retrieval + Evidence Intelligence.

Every retrieval and Evidence Intelligence line printed traces back to a
real `ke evidence-report`/`ke evidence-intelligence` field. `--synthesize`
is the one opt-in exception: a local, offline LLM narrates that same
already-computed evidence into a paragraph -- see `docs/ai_design.md`'s
"Decision: local LLM" section and `knowledge_engine_ai/synthesis.py`.

`research` (AI-O12) is a second, separate path: it runs the full composed
orchestrator -- durable session, parallel retrieval, Skeptic-verified
synthesis, ISA close gate, full trace -- rather than `ask`'s direct
retrieval-plus-narration call. See
`knowledge_engine_ai/copilot/run_research_question.py`.
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

from knowledge_engine_ai.copilot.run_research_question import (
    ResearchQuestionResult,
    run_research_question,
)
from knowledge_engine_ai.ke_client import (
    FederatedDiscoveryResult,
    KeCommandError,
    enriched_evidence_report,
    federated_discover,
)
from knowledge_engine_ai.llm import DEFAULT_OLLAMA_HOST, LocalLLMError, OllamaLLM
from knowledge_engine_ai.models import EvidenceReport
from knowledge_engine_ai.orchestrator.observability import render_session_trace
from knowledge_engine_ai.sessions.repository import SessionRepository, new_connection
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
SessionDbOption = Annotated[
    Path | None,
    typer.Option(
        "--session-db",
        help=(
            "SQLite database path for durable Research Copilot sessions. Falls back to "
            "KE_AI_SESSION_DB_PATH, then './research_sessions.db' in the current directory."
        ),
    ),
]


DiscoveryQueryArgument = Annotated[
    str, typer.Argument(help="Provider-neutral free-text discovery query.")
]
LedgerRootOption = Annotated[
    Path,
    typer.Option(
        "--ledger-root",
        help="Directory Core's federated search-run ledger persists JSON run records to.",
    ),
]
DiscoveryProvidersOption = Annotated[
    str | None,
    typer.Option(
        "--providers",
        help=(
            "Comma-separated provider subset (e.g. 'pubmed,openalex'). "
            "Defaults to every provider Core has configured."
        ),
    ),
]
OpenAlexApiKeyOption = Annotated[
    str | None,
    typer.Option(
        "--openalex-api-key",
        envvar="KE_AI_OPENALEX_API_KEY",
        help="Optional OpenAlex API key, forwarded to `ke federated-discover`.",
    ),
]
SemanticScholarApiKeyOption = Annotated[
    str | None,
    typer.Option(
        "--semantic-scholar-api-key",
        envvar="KE_AI_SEMANTIC_SCHOLAR_API_KEY",
        help="Optional Semantic Scholar API key, forwarded to `ke federated-discover`.",
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


@app.command()
def research(
    question: QuestionArgument,
    sources: SourcesOption,
    evidence: EvidenceOption,
    llm_model: LlmModelOption = None,
    ollama_host: OllamaHostOption = None,
    session_db: SessionDbOption = None,
    limit: LimitOption = 5,
    output_format: FormatOption = "text",
) -> None:
    """Run the composed AI-O12 orchestrator pipeline for one research question.

    Unlike `ask --synthesize`, which calls `enriched_evidence_report` and
    `synthesize_answer` directly, this command runs the full composed
    pipeline: a durable session is created (AI-O2), primary and
    contradiction-oriented retrieval run together (AI-O5), the answer is
    synthesized and independently Skeptic-verified (AI-O6), resolved into
    sourced claims (AI-O7), the session's Research ISA close gate is
    evaluated (AI-O2/AI-O12), and a full trace is assembled (AI-O9) --
    every step recorded as a durable, inspectable `ResearchEvent`, not
    just printed and discarded. This is this repo's own first caller of
    that composed pipeline, exercising it before `knowledge-engine-web`
    ever does (AI-O14).
    """

    if output_format not in ("text", "json"):
        raise typer.BadParameter("--format must be 'text' or 'json'.")

    model = llm_model or os.environ.get("KE_AI_LLM_MODEL")
    if model is None:
        console.print("[red]Error:[/red] research requires --llm-model or KE_AI_LLM_MODEL.")
        raise typer.Exit(1)
    host = ollama_host or os.environ.get("KE_AI_OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
    llm = OllamaLLM(model=model, host=host)

    db_path = session_db or Path(os.environ.get("KE_AI_SESSION_DB_PATH", "research_sessions.db"))
    session_repository = SessionRepository(new_connection(str(db_path)))

    try:
        result = run_research_question(
            question,
            session_repository=session_repository,
            sources=sources,
            evidence=evidence,
            llm=llm,
            limit=limit,
        )
    except KeCommandError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_format == "json":
        payload = {
            "session_id": result.session_id,
            "question": result.question,
            "narrative": result.narrative,
            "narrative_releaseable": result.narrative_releaseable,
            "synthesis_error": result.synthesis_error,
            "verification": (
                None
                if result.verification is None
                else {
                    "is_clean": result.verification.is_clean,
                    "hallucinated_citations": list(result.verification.hallucinated_citations),
                    "ungrounded_numbers": list(result.verification.ungrounded_numbers),
                    "missed_qualifiers": list(result.verification.missed_qualifiers),
                }
            ),
            "close_status": result.close_result.status.value,
            "close_complete": result.close_result.validation.complete,
            "unresolved_required_criteria": list(
                result.close_result.validation.unresolved_required_criteria
            ),
            "trace": render_session_trace(result.trace),
        }
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return

    _print_research_result(result)


def _print_research_result(result: ResearchQuestionResult) -> None:
    console.print(f"[bold]Session:[/bold] {result.session_id}")
    console.print(f"[bold]Question:[/bold] {result.question}")
    console.print()

    if result.narrative is None:
        if result.synthesis_error is not None:
            console.print(f"[red]Synthesis failed:[/red] {escape(result.synthesis_error)}")
        else:
            console.print(
                "[yellow]No evidence with a stated claim was retrieved to narrate.[/yellow]"
            )
    elif result.narrative_releaseable:
        console.print("[bold]Synthesized answer[/bold] (local model, Skeptic-verified):")
        console.print(escape(result.narrative))
        console.print()
        verification = result.verification
        if verification is None:  # pragma: no cover - narrative implies verification ran.
            raise AssertionError("A narrative was produced without a verification result.")
        if verification.is_clean:
            console.print(
                "[green]Skeptic verification: clean[/green] -- no hallucinated citations, "
                "ungrounded numbers, or omitted qualifying evidence found."
            )
        else:
            console.print("[yellow]Skeptic verification flagged issues:[/yellow]")
            if verification.hallucinated_citations:
                console.print(
                    f"  Hallucinated citations: {', '.join(verification.hallucinated_citations)}"
                )
            if verification.ungrounded_numbers:
                console.print(f"  Ungrounded numbers: {', '.join(verification.ungrounded_numbers)}")
            if verification.missed_qualifiers:
                console.print(
                    f"  Missed qualifying evidence: {', '.join(verification.missed_qualifiers)}"
                )
    else:
        console.print(
            "[yellow]Draft narrative withheld:[/yellow] deterministic verification or the "
            "Research ISA close gate did not pass. Inspect the durable session for details."
        )

    console.print()
    status = result.close_result.status.value
    status_color = "green" if result.close_result.validation.complete else "yellow"
    console.print(f"[bold]Session status:[/bold] [{status_color}]{status}[/{status_color}]")
    if not result.close_result.validation.complete:
        unresolved = ", ".join(result.close_result.validation.unresolved_required_criteria)
        console.print(f"  Unresolved required criteria: {unresolved}")

    console.print()
    console.print(escape(render_session_trace(result.trace)))


@app.command()
def discover(
    query: DiscoveryQueryArgument,
    ledger_root: LedgerRootOption,
    limit: LimitOption = 20,
    providers: DiscoveryProvidersOption = None,
    openalex_api_key: OpenAlexApiKeyOption = None,
    semantic_scholar_api_key: SemanticScholarApiKeyOption = None,
    output_format: FormatOption = "text",
) -> None:
    """Run one federated discovery search via Core's `ke federated-discover`.

    This repository's `ke_client.federated_discover()` (the one supported
    subprocess boundary for invoking Core, per `docs/agent-development-policy.md`)
    was implemented, unit-tested, and live-verified against the real `ke`
    binary, but had no caller inside this repository -- only
    `knowledge-engine-web`'s `/discover` route used it. This command is that
    caller: a direct, bounded way to run and inspect one federated discovery
    search from `knowledge-engine-ai` itself, without a full Research Copilot
    session. It is deliberately *not* wired into `run_research_question`'s
    own planning -- that is AI-FRD-3's (Discovery-plan compiler) job once
    Research Copilot can decide *when* broader provider coverage is needed,
    a judgment this command does not make. See
    `docs/roadmap/federated_discovery_orchestration_adoption.md`.

    Every provider's status printed is Core's own recorded outcome -- never
    inferred from result count -- and provider-metadata disagreement (when
    Core's snapshot includes it) is shown as a metadata-quality fact, never
    reinterpreted as scientific contradiction or evidence strength.
    """

    if output_format not in ("text", "json"):
        raise typer.BadParameter("--format must be 'text' or 'json'.")

    provider_names = _parse_discovery_providers(providers)

    try:
        result = federated_discover(
            query,
            ledger_root=ledger_root,
            limit=limit,
            providers=provider_names,
            openalex_api_key=openalex_api_key,
            semantic_scholar_api_key=semantic_scholar_api_key,
        )
    except KeCommandError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_format == "json":
        sys.stdout.write(json.dumps(dataclasses.asdict(result), indent=2, sort_keys=True) + "\n")
        return

    _print_discovery_result(result)


def _parse_discovery_providers(providers: str | None) -> tuple[str, ...] | None:
    if providers is None:
        return None
    names = tuple(name.strip() for name in providers.split(",") if name.strip())
    if not names:
        raise typer.BadParameter("--providers must name at least one provider when given.")
    return names


def _print_discovery_result(result: FederatedDiscoveryResult) -> None:
    console.print(f"[bold]Search run:[/bold] {result.search_run_id}")
    completeness_color = {
        "complete": "green",
        "partial": "yellow",
        "failed": "red",
    }.get(result.completeness, "white")
    console.print(
        f"[bold]Coverage:[/bold] "
        f"[{completeness_color}]{result.completeness}[/{completeness_color}] "
        f"({len(result.candidates)} deduplicated candidate(s))"
    )
    for status in result.provider_statuses:
        reason = f" ({status.reason})" if status.reason else ""
        console.print(f"  {status.provider}: {status.outcome}{reason}")
    console.print()

    if result.provider_disagreements is None:
        console.print("[dim]This search run predates provider-disagreement reporting.[/dim]")
    else:
        disagreement_count = sum(
            len(candidate.disagreements) > 0 for candidate in result.provider_disagreements
        )
        console.print(
            f"[bold]Provider metadata disagreements:[/bold] {disagreement_count} candidate(s) "
            "-- metadata-quality facts, not scientific contradiction."
        )
    console.print()

    if not result.candidates:
        console.print("[yellow]No candidates found by any searched provider.[/yellow]")
        return

    for candidate in result.candidates:
        year = f" ({candidate.publication_year})" if candidate.publication_year else ""
        doi = f" -- DOI {candidate.doi}" if candidate.doi else ""
        console.print(f"[bold]{escape(candidate.title)}[/bold]{year}{doi}")
        console.print(f"  observed by: {', '.join(candidate.providers)}")

    console.print()
    console.print(
        "[bold]Discovery only -- these are not Evidence Records and were not acquired.[/bold]"
    )
