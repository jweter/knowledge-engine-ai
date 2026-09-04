from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def run_step(argv: list[str], root: Path) -> int:
    print("+ " + " ".join(argv), flush=True)
    result = subprocess.run(argv, cwd=root, check=False)
    return result.returncode


def git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run canonical repository preflight.")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply the repository-approved formatter before validation.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run only checks marked safe for pre-commit use.",
    )
    parser.add_argument(
        "--evidence",
        default="preflight-evidence.json",
        help="Path for machine-readable preflight evidence.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    control = json.loads(
        (root / "engineering" / "control-plane.json").read_text(encoding="utf-8")
    )
    preflight = control["preflight"]
    evidence_path = root / args.evidence

    formatter = preflight.get("format_apply")
    if args.fix and formatter is not None and run_step(formatter, root) != 0:
        return 1

    results: list[dict[str, object]] = []
    overall = "GREEN"
    for check in preflight["checks"]:
        if args.fast and not check["fast"]:
            continue
        returncode = run_step(check["argv"], root)
        status = "PASS" if returncode == 0 else "FAIL"
        results.append(
            {
                "id": check["id"],
                "kind": check["kind"],
                "status": status,
                "returncode": returncode,
            }
        )
        if returncode != 0:
            overall = "FAILED"
            break

    evidence = {
        "schema_version": 1,
        "repository": control["repository"],
        "head_sha": git_head(root),
        "mode": "FAST" if args.fast else "FULL",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": overall,
        "checks": results,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))

    return 0 if overall == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
