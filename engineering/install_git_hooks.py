from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    hook = root / ".githooks" / "pre-commit"
    hook.chmod(0o755)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=root,
        check=True,
    )
    print("Configured repository hooks: .githooks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
