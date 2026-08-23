"""Run Knowledge Engine AI's local quality gates with optional safe autofix."""

from __future__ import annotations

import argparse
import subprocess as subprocess
import sys
from collections.abc import Sequence

Command = tuple[str, ...]

FIXES: tuple[Command, ...] = (
    ("ruff", "format", "."),
    ("ruff", "check", "--fix", "."),
    ("ruff", "format", "."),
)

CHECKS: tuple[Command, ...] = (
    ("ruff", "format", "--check", "--diff", "."),
    ("ruff", "check", "."),
    ("mypy", "knowledge_engine_ai", "tests"),
    ("pytest",),
    ("pip-audit",),
    ("git", "diff", "--check"),
)


def _run(command: Command) -> int:
    print(f"+ {' '.join(command)}", flush=True)
    return subprocess.run(command, check=False).returncode  # noqa: S603


def run(commands: Sequence[Command]) -> int:
    """Run commands in order and stop at the first failure."""
    for command in commands:
        returncode = _run(command)
        if returncode != 0:
            return returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run safe autofix first when requested, then the complete CI-parity checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply Ruff's safe fixes and canonical formatting before validation.",
    )
    args = parser.parse_args(argv)

    if args.fix:
        returncode = run(FIXES)
        if returncode != 0:
            return returncode
    return run(CHECKS)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
