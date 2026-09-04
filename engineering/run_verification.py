from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run executable control-plane verification lanes.")
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        help="Lane id to run; repeatable. Defaults to all.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "engineering" / "control-plane.json").read_text(encoding="utf-8"))
    lanes = data["verification"]["executable_lanes"]
    wanted = set(args.lane)
    selected = [lane for lane in lanes if not wanted or lane["id"] in wanted]
    missing = wanted - {lane["id"] for lane in selected}

    if missing:
        print("unknown lane(s): " + ", ".join(sorted(missing)), file=sys.stderr)
        return 2

    for lane in selected:
        print(f"=== verification lane: {lane['id']} ===", flush=True)
        for step in lane["steps"]:
            print("+ " + " ".join(step), flush=True)
            result = subprocess.run(step, cwd=root, check=False)
            if result.returncode:
                print(
                    f"lane {lane['id']} FAILED with exit code {result.returncode}",
                    file=sys.stderr,
                )
                return result.returncode
        print(f"lane {lane['id']} PASS", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
