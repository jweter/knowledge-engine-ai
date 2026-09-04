from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


STATES = (
    "IMPLEMENTING",
    "PREFLIGHT_UNVERIFIED",
    "PREFLIGHT_GREEN",
    "PR_OPEN",
    "CI_PENDING",
    "GREEN",
    "MERGED",
    "PRODUCT_REALITY_PENDING",
    "PRODUCT_REALITY_VERIFIED",
)


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
    parser = argparse.ArgumentParser(description="Report local promotion readiness.")
    parser.add_argument("--evidence", default="preflight-evidence.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    evidence_path = root / args.evidence
    head = git_head(root)

    if not evidence_path.is_file():
        state = "PREFLIGHT_UNVERIFIED"
        reason = "no preflight evidence for the current HEAD"
    else:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("head_sha") != head or evidence.get("mode") != "FULL":
            state = "PREFLIGHT_UNVERIFIED"
            reason = "full preflight evidence does not match current HEAD"
        elif evidence.get("status") == "GREEN":
            state = "PREFLIGHT_GREEN"
            reason = "canonical full preflight passed on current HEAD"
        else:
            state = "IMPLEMENTING"
            reason = "canonical full preflight is not green"

    payload = {
        "schema_version": 1,
        "state": state,
        "reason": reason,
        "head_sha": head,
        "allowed_states": STATES,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
