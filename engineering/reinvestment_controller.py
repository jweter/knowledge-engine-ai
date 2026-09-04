from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

UNKNOWN = "UNKNOWN"
MAX_SYSTEM_REINVESTMENT = 0.20
MIN_SYSTEM_REINVESTMENT = 0.05


def load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 2:
        raise SystemExit("compounding report schema_version must be 2")
    if not isinstance(payload.get("windows"), dict):
        raise SystemExit("compounding report windows are required")
    if not isinstance(payload.get("evidence_derived"), dict):
        raise SystemExit("compounding report evidence_derived is required")
    return payload


def numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def bounded(value: float) -> float:
    return round(
        min(MAX_SYSTEM_REINVESTMENT, max(MIN_SYSTEM_REINVESTMENT, value)),
        4,
    )


def recommend(report: dict[str, Any]) -> dict[str, Any]:
    evidence = report["evidence_derived"]
    current = report["windows"].get("current") or {}

    throughput = numeric(evidence.get("throughput_factor"))
    cycle = numeric(evidence.get("cycle_time_factor"))
    emf = numeric(evidence.get("engineering_multiplication_factor"))
    compounding = numeric(evidence.get("compounding_rate"))
    repeat_failure = numeric(current.get("repeat_failure_rate"))
    unlock_rate = numeric(current.get("dependency_unlock_rate"))
    human_rate = numeric(current.get("human_intervention_rate"))

    investment = MIN_SYSTEM_REINVESTMENT
    actions: list[dict[str, Any]] = []
    reasons: list[str] = []

    if repeat_failure is None:
        investment += 0.02
        actions.append(
            {
                "priority": 20,
                "kind": "MEASUREMENT",
                "target": "failure_recurrence",
            }
        )
        reasons.append("repeat-failure evidence is insufficient")
    elif repeat_failure >= 0.25:
        investment += 0.08
        actions.append(
            {
                "priority": 90,
                "kind": "REGRESSION_HARDENING",
                "target": "repeated_failures",
            }
        )
        reasons.append("repeat-failure rate is elevated")

    if cycle is not None and cycle < 0.90:
        investment += 0.05
        actions.append(
            {
                "priority": 70,
                "kind": "CYCLE_TIME_COMPRESSION",
                "target": "wip_and_feedback_latency",
            }
        )
        reasons.append("PR cycle-time factor is regressing")

    if unlock_rate is None:
        investment += 0.01
        actions.append(
            {
                "priority": 15,
                "kind": "MEASUREMENT",
                "target": "dependency_unlocks",
            }
        )
        reasons.append("dependency-unlock evidence is insufficient")
    elif unlock_rate <= 0:
        investment += 0.03
        actions.append(
            {
                "priority": 55,
                "kind": "BLOCKER_DISCOVERY",
                "target": "dependency_unlocks",
            }
        )
        reasons.append("no explicit downstream unlocks were observed")

    if human_rate is not None and human_rate >= 0.50:
        investment += 0.03
        actions.append(
            {
                "priority": 45,
                "kind": "AUTOMATION_FRICTION",
                "target": "avoidable_human_intervention",
            }
        )
        reasons.append("human-intervention proxy is high")

    if emf is not None and emf > 1.0 and compounding is not None and compounding > 0:
        investment -= 0.04
        actions.append(
            {
                "priority": 40,
                "kind": "PRODUCT_BIAS",
                "target": "direct_roadmap_delivery",
            }
        )
        reasons.append("measured throughput/cycle-time evidence is improving")

    if throughput is not None and throughput < 1.0:
        investment += 0.03
        actions.append(
            {
                "priority": 60,
                "kind": "THROUGHPUT_RECOVERY",
                "target": "delivery_bottlenecks",
            }
        )
        reasons.append("merged-PR throughput factor is below one")

    system_fraction = bounded(investment)
    product_fraction = round(1.0 - system_fraction, 4)
    actions.sort(key=lambda row: (-int(row["priority"]), str(row["kind"])))

    confidence = "EVIDENCE_LIMITED"
    known = sum(
        value is not None
        for value in (
            throughput,
            cycle,
            emf,
            compounding,
            repeat_failure,
            unlock_rate,
            human_rate,
        )
    )
    if known >= 6:
        confidence = "MODERATE"
    if known == 7:
        confidence = "HIGH"

    return {
        "schema_version": 1,
        "system_reinvestment_fraction": system_fraction,
        "product_delivery_fraction": product_fraction,
        "confidence": confidence,
        "actions": actions,
        "reasons": reasons,
        "guardrails": {
            "max_system_reinvestment_fraction": MAX_SYSTEM_REINVESTMENT,
            "min_system_reinvestment_fraction": MIN_SYSTEM_REINVESTMENT,
            "never_override_p0_p1_or_existing_work": True,
            "never_bypass_preflight_or_required_ci": True,
            "never_auto_accept_product_reality": True,
            "recommendations_are_advisory": True,
        },
    }


def self_test() -> list[str]:
    errors: list[str] = []
    report = {
        "schema_version": 2,
        "windows": {
            "current": {
                "repeat_failure_rate": 0.50,
                "dependency_unlock_rate": 0.0,
                "human_intervention_rate": 0.75,
            }
        },
        "evidence_derived": {
            "throughput_factor": 0.8,
            "cycle_time_factor": 0.8,
            "engineering_multiplication_factor": 0.64,
            "compounding_rate": -0.1,
        },
    }
    result = recommend(report)
    if result["system_reinvestment_fraction"] != MAX_SYSTEM_REINVESTMENT:
        errors.append("degraded evidence should reach bounded max reinvestment")
    if result["product_delivery_fraction"] != 0.8:
        errors.append("product/system fractions must sum to one")
    if not any(row["kind"] == "REGRESSION_HARDENING" for row in result["actions"]):
        errors.append("repeat failures must trigger regression hardening")

    healthy = {
        "schema_version": 2,
        "windows": {
            "current": {
                "repeat_failure_rate": 0.0,
                "dependency_unlock_rate": 0.2,
                "human_intervention_rate": 0.1,
            }
        },
        "evidence_derived": {
            "throughput_factor": 1.2,
            "cycle_time_factor": 1.1,
            "engineering_multiplication_factor": 1.32,
            "compounding_rate": 0.1,
        },
    }
    healthy_result = recommend(healthy)
    if healthy_result["system_reinvestment_fraction"] != MIN_SYSTEM_REINVESTMENT:
        errors.append("healthy evidence should return to minimum reinvestment")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert compounding evidence into bounded reinvestment guidance."
    )
    parser.add_argument("--report")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        errors = self_test()
        if errors:
            print(json.dumps({"status": "FAILED", "errors": errors}, indent=2))
            return 1
        print(json.dumps({"status": "GREEN"}, indent=2))
        return 0

    if not args.report:
        raise SystemExit("--report is required unless --self-test is used")
    result = recommend(load_report(Path(args.report)))
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
