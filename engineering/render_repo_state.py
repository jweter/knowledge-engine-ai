from __future__ import annotations

import json
import shutil
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "engineering" / "control-plane.json").read_text(encoding="utf-8")
    )
    docs_ok = all((root / path).is_file() for path in data["authoritative_documents"])

    lane_state: dict[str, str] = {}
    for lane in data["verification"]["executable_lanes"]:
        first = lane["steps"][0][0]
        lane_state[lane["id"]] = (
            "AVAILABLE"
            if (shutil.which(first) or (root / first).exists())
            else "ENVIRONMENT_MISSING"
        )

    output = {
        "schema_version": 1,
        "project": data["portfolio_project"],
        "repository": data["repository"],
        "control_plane_contract": "VERIFIED" if docs_ok else "INVALID",
        "authoritative_documents": "VERIFIED" if docs_ok else "INVALID",
        "executable_verification": lane_state,
        "product_reality": {
            lane: "UNVERIFIED"
            for lane in data["verification"]["product_reality_lanes"]
        },
        "readiness_dimensions": {
            dimension: "UNKNOWN"
            for dimension in data["readiness_scoring"]["dimensions"]
        },
        "continuation": data["continuation"],
    }
    output["readiness_dimensions"]["documentation"] = (
        "VERIFIED" if docs_ok else "BLOCKED"
    )

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if docs_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
