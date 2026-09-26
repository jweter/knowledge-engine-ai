"""CLI for the unattended Monster #79 acceptance bridge.

Run as `python -m knowledge_engine_ai.monster_acceptance_cli` on the local worker
after the normal research path has written its artifacts. Missing artifact files
are passed through as missing so the bridge fails closed; only the sanitized
evidence document is written. Exit status is 0 only for `PASS`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from knowledge_engine_ai.monster_acceptance import evaluate_monster_acceptance
from knowledge_engine_ai.unattended_acceptance import UnattendedAcceptanceManifest

app = typer.Typer(add_completion=False)

ManifestOption = Annotated[
    Path,
    typer.Option(
        "--manifest", exists=True, dir_okay=False, help="UnattendedAcceptanceManifest JSON."
    ),
]
OutputOption = Annotated[
    Path | None,
    typer.Option("--output", help="Sanitized evidence JSON path; stdout when omitted."),
]


@app.command()
def evaluate(
    manifest: ManifestOption,
    worker_result: Annotated[
        Path, typer.Option("--worker-result", dir_okay=False, help="Core WorkerResult JSON.")
    ],
    runtime_identity: Annotated[
        Path,
        typer.Option(
            "--runtime-identity",
            dir_okay=False,
            help="Observed AI/Core/Web SHAs and Ollama model/runtime JSON.",
        ),
    ],
    research_result: Annotated[
        Path,
        typer.Option(
            "--research-result", dir_okay=False, help="`ke-ai research --format json` output."
        ),
    ],
    research_report: Annotated[
        Path,
        typer.Option("--research-report", dir_okay=False, help="ResearchReport.to_dict() JSON."),
    ],
    benchmark_facts: Annotated[
        Path,
        typer.Option(
            "--benchmark-facts", dir_okay=False, help="Structured golden-case facts JSON."
        ),
    ],
    output: OutputOption = None,
) -> None:
    """Score one unattended Monster run and emit sanitized acceptance evidence."""

    manifest_data = _read_json(manifest)
    if manifest_data is None:
        raise typer.BadParameter("--manifest must contain a JSON object.")
    try:
        bound_manifest = UnattendedAcceptanceManifest(
            **{**manifest_data, "requested_checks": tuple(manifest_data["requested_checks"])}
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise typer.BadParameter(f"--manifest is invalid: {exc}") from exc

    evidence = evaluate_monster_acceptance(
        bound_manifest,
        worker_result=_read_json(worker_result),
        observed_runtime_identity=_read_json(runtime_identity),
        research_result=_read_json(research_result),
        research_report=_read_json(research_report),
        benchmark_facts=_read_json(benchmark_facts),
    )
    payload = json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(payload)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        typer.echo(str(output))
    if not evidence.passes:
        raise typer.Exit(1)


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return a JSON object, or None when the artifact is absent or not an object."""

    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


if __name__ == "__main__":
    app()
