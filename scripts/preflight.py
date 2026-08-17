"""Run the same local quality gates enforced by the AI repository CI."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence


CHECKS: tuple[tuple[str, ...], ...] = (
    ("ruff", "format", "--check", "--diff", "."),
    ("ruff", "check", "."),
    ("mypy", "knowledge_engine_ai", "tests"),
    ("pytest",),
    ("pip-audit",),
    ("git", "diff", "--check"),
)


def _run(command: Sequence[str]) -> int:
    print(f"+ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    """Run CI-parity checks in fail-fast order."""

    for command in CHECKS:
        returncode = _run(command)
        if returncode != 0:
            return returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
