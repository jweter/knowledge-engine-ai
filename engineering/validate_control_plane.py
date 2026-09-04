from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REQUIRED_TOP = {
    "schema_version",
    "portfolio_project",
    "repository",
    "repository_role",
    "source_of_truth",
    "authoritative_documents",
    "definition_of_done",
    "invariants",
    "verification",
    "work_ownership",
    "regression_memory",
    "readiness_scoring",
    "continuation",
    "portfolio_aggregation",
    "golden_scenarios",
}


def fail(messages: list[str]) -> int:
    for message in messages:
        print(f"CONTROL_PLANE_ERROR: {message}", file=sys.stderr)
    return 1


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "engineering" / "control-plane.json"
    errors: list[str] = []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail([f"cannot load {path.relative_to(root)}: {exc}"])

    missing = sorted(REQUIRED_TOP - set(data))
    if missing:
        errors.append("missing top-level keys: " + ", ".join(missing))

    if data.get("schema_version") != 3:
        errors.append("schema_version must be 3")

    repository = data.get("repository")
    github_repository = os.getenv("GITHUB_REPOSITORY")
    if not isinstance(repository, str) or "/" not in repository:
        errors.append("repository must be owner/name")
    if github_repository and repository != github_repository:
        errors.append(
            f"repository {repository!r} does not match GITHUB_REPOSITORY "
            f"{github_repository!r}"
        )

    documents = data.get("authoritative_documents")
    if not isinstance(documents, list) or not documents:
        errors.append("authoritative_documents must be a non-empty list")
    else:
        for item in documents:
            if not isinstance(item, str) or not item:
                errors.append(
                    "authoritative_documents entries must be non-empty strings"
                )
                continue
            target = (root / item).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                errors.append(f"authoritative document escapes repository: {item}")
                continue
            if not target.is_file():
                errors.append(f"authoritative document does not exist: {item}")

    invariants = data.get("invariants")
    if (
        not isinstance(invariants, list)
        or not invariants
        or len(invariants) != len(set(invariants))
    ):
        errors.append("invariants must be a non-empty unique list")

    aggregation = data.get("portfolio_aggregation")
    if not isinstance(aggregation, dict):
        errors.append("portfolio_aggregation must be an object")
    else:
        if not aggregation.get("project_key"):
            errors.append("portfolio_aggregation.project_key is required")
        if not aggregation.get("component_role"):
            errors.append("portfolio_aggregation.component_role is required")
        required = aggregation.get("required_components")
        if not isinstance(required, list) or not required:
            errors.append(
                "portfolio_aggregation.required_components must be non-empty"
            )

    verification = data.get("verification")
    executable_ids: set[str] = set()
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
    else:
        executable = verification.get("executable_lanes")
        if not isinstance(executable, list) or not executable:
            errors.append("verification.executable_lanes must be non-empty")
        else:
            for lane in executable:
                if not isinstance(lane, dict):
                    errors.append("each executable lane must be an object")
                    continue
                lane_id = lane.get("id")
                steps = lane.get("steps")
                if not isinstance(lane_id, str) or not lane_id:
                    errors.append("each executable lane requires a non-empty id")
                else:
                    if lane_id in executable_ids:
                        errors.append(
                            "verification.executable_lanes ids must be unique"
                        )
                    executable_ids.add(lane_id)
                if not isinstance(steps, list) or not steps:
                    errors.append(
                        f"executable lane {lane_id!r} requires non-empty steps"
                    )
                else:
                    for step in steps:
                        if (
                            not isinstance(step, list)
                            or not step
                            or not all(isinstance(value, str) and value for value in step)
                        ):
                            errors.append(
                                f"executable lane {lane_id!r} contains an invalid "
                                "argv step"
                            )

    scenarios = data.get("golden_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("golden_scenarios must be a non-empty list")
    else:
        scenario_ids: set[str] = set()
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                errors.append("each golden scenario must be an object")
                continue
            scenario_id = scenario.get("id")
            lane_id = scenario.get("lane")
            if not isinstance(scenario_id, str) or not scenario_id:
                errors.append("each golden scenario requires a non-empty id")
            elif scenario_id in scenario_ids:
                errors.append("golden_scenarios ids must be unique")
            else:
                scenario_ids.add(scenario_id)
            if lane_id not in executable_ids:
                errors.append(
                    f"golden scenario {scenario_id!r} references unknown lane "
                    f"{lane_id!r}"
                )

    memory = data.get("regression_memory")
    if not isinstance(memory, dict):
        errors.append("regression_memory must be an object")
    else:
        memory_path = memory.get("path")
        if not isinstance(memory_path, str) or not memory_path:
            errors.append("regression_memory.path is required")
        elif not (root / memory_path).is_file():
            errors.append(f"regression memory does not exist: {memory_path}")

    scoring = data.get("readiness_scoring")
    if (
        not isinstance(scoring, dict)
        or scoring.get("prohibit_guessed_percent_complete") is not True
    ):
        errors.append("readiness_scoring must prohibit guessed percent complete")

    if errors:
        return fail(errors)

    print(f"control-plane contract valid for {repository}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
