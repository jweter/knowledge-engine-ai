"""CLI for the deterministic three-domain retrieval baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from knowledge_engine_ai.ke_client import KeCommandError
from knowledge_engine_ai.retrieval_baseline import run_retrieval_baseline

app = typer.Typer(add_completion=False)

CoreRootOption = Annotated[
    Path,
    typer.Option(
        "--core-root",
        help="Path to the knowledge-engine-core checkout containing reviewed corpora.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
]
AiRootOption = Annotated[
    Path | None,
    typer.Option(
        "--ai-root",
        help="Path to this AI checkout. Defaults to the installed package checkout.",
        file_okay=False,
        dir_okay=True,
    ),
]
LimitOption = Annotated[int, typer.Option("--limit", "-n", min=1, max=100)]
KeExecutableOption = Annotated[
    str,
    typer.Option("--ke-executable", help="Core CLI executable name or path."),
]


@app.command()
def run(
    core_root: CoreRootOption,
    ai_root: AiRootOption = None,
    limit: LimitOption = 10,
    ke_executable: KeExecutableOption = "ke",
) -> None:
    """Run the reviewed cross-domain retrieval baseline and emit reproducible JSON."""

    resolved_ai_root = ai_root or Path(__file__).resolve().parents[1]
    try:
        payload = run_retrieval_baseline(
            core_root=core_root.resolve(),
            ai_root=resolved_ai_root.resolve(),
            limit=limit,
            ke_executable=ke_executable,
        )
    except (FileNotFoundError, KeCommandError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
