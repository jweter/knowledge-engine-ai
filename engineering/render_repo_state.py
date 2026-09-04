from __future__ import annotations

import json
import shutil
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    control = json.loads(
        (root / "engineering" / "control-plane.json").read_text(encoding="utf-8")
    )
    memory = json.loads(
        (root / "engineering" / "regression-memory.json").read_text(encoding="utf-8")
    )
    docs_ok = all((root / path).is_file() for path in control["authoritative_documents"])

    lane_state: dict[str, str] = {}
    for lane in control["verification"]["executable_lanes"]:
        first = lane["steps"][0][0]
        lane_state[lane["id"]] = (
            "AVAILABLE"
            if (shutil.which(first) or (root / first).exists())
            else "ENVIRONMENT_MISSING"
        )

    output = {
        "schema_version": 3,
        "project": control["portfolio_project"],
        "project_key": control["portfolio_aggregation"]["project_key"],
        "repository": control["repository"],
        "component_role": control["portfolio_aggregation"]["component_role"],
        "required_components": control["portfolio_aggregation"]["required_components"],
        "control_plane_contract": "VERIFIED" if docs_ok else "INVALID",
        "authoritative_documents": "VERIFIED" if docs_ok else "INVALID",
        "executable_verification": lane_state,
        "golden_scenarios": {
            scenario["id"]: {
                "component": scenario["component"],
                "lane": scenario["lane"],
                "status": "DECLARED",
            }
            for scenario in control["golden_scenarios"]
        },
        "preflight": {
            "required_before_pr": control["preflight"]["required_before_pr"],
            "evidence_file": control["preflight"]["evidence_file"],
            "status": "UNVERIFIED",
        },
        "promotion": {
            "states": control["promotion"]["states"],
            "status": "IMPLEMENTING",
        },
        "regression_memory": {
            "recorded_incidents": len(memory["entries"]),
            "status": "VERIFIED",
        },
        "product_reality": {
            lane: "UNVERIFIED" for lane in control["verification"]["product_reality_lanes"]
        },
        "readiness_dimensions": {
            dimension: "UNKNOWN" for dimension in control["readiness_scoring"]["dimensions"]
        },
        "continuation": control["continuation"],
    }
    output["readiness_dimensions"]["documentation"] = "VERIFIED" if docs_ok else "BLOCKED"

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if docs_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
