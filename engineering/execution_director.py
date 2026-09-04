from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "engineering" / "control-plane.json"
LEARNING = ROOT / "engineering" / "learning-memory.json"
ATTESTATIONS = ROOT / "engineering" / "product-reality-attestations.json"
DEPENDENCIES = ROOT / "engineering" / "portfolio-dependencies.json"
PRIVATE_INBOX = ROOT / "private" / "product-reality-inbox"

SEVERITY = {"P0": 100, "P1": 80, "P2": 60, "P3": 40, "P4": 30, "P5": 20, "P6": 10}


def load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def github(path: str) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-execution-director",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def pages(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 51):
        batch = github(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise SystemExit(f"Expected list response for {path}")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise SystemExit(f"Pagination safety limit exceeded for {path}")


def workflow_learning() -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=14)
    events = []
    for run in pages("/actions/runs?status=completed"):
        created = run.get("created_at")
        if not created:
            continue
        when = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if when < cutoff:
            break
        conclusion = run.get("conclusion")
        if conclusion not in {"failure", "cancelled", "timed_out", "action_required"}:
            continue
        events.append(
            {
                "type": "workflow_failure",
                "workflow": run.get("name"),
                "conclusion": conclusion,
                "head_sha": run.get("head_sha"),
                "run_id": run.get("id"),
                "recorded_at": created,
            }
        )
    return events


def review_learning() -> list[dict[str, Any]]:
    events = []
    for pr in pages("/pulls?state=all&sort=updated&direction=desc"):
        number = pr["number"]
        for comment in pages(f"/pulls/{number}/comments"):
            body = str(comment.get("body") or "")
            if not body:
                continue
            if not any(marker in body for marker in ("P0 Badge", "P1 Badge", "P2 Badge")):
                continue
            events.append(
                {
                    "type": "review_finding",
                    "pull_request": number,
                    "comment_id": comment.get("id"),
                    "summary": body[:500],
                    "recorded_at": comment.get("created_at"),
                }
            )
        if len(events) >= 50:
            break
    return events[:50]


def fingerprint(event: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def merged_learning(existing: dict[str, Any]) -> dict[str, Any]:
    events = list(existing.get("events", []))
    seen = {event.get("fingerprint") for event in events}
    for event in workflow_learning() + review_learning():
        key = fingerprint(event)
        if key in seen:
            continue
        event["fingerprint"] = key
        events.append(event)
        seen.add(key)
    return {
        "schema_version": 1,
        "events": events[-250:],
        "rule": "sanitized lessons only; never store secrets or private Product Reality payloads",
    }


def harvest_product_reality(control: dict[str, Any]) -> dict[str, Any]:
    repo = control["repository"]
    allowed = set(control.get("verification", {}).get("product_reality_lanes", []))
    current = load(
        ATTESTATIONS,
        {"schema_version": 1, "repository": repo, "lanes": {}},
    )
    if current.get("repository") != repo:
        raise SystemExit("Product Reality attestation repository mismatch")
    PRIVATE_INBOX.mkdir(parents=True, exist_ok=True)
    for path in sorted(PRIVATE_INBOX.glob("*.json")):
        payload = load(path, None)
        if not isinstance(payload, dict):
            continue
        lane = str(payload.get("lane") or "")
        status = str(payload.get("status") or "").upper()
        if lane not in allowed or status not in {"PASS", "FAIL", "PENDING", "BLOCKED"}:
            continue
        refs = payload.get("evidence_refs") or []
        if status == "PASS" and not refs:
            continue
        current["lanes"][lane] = {
            "status": status,
            "head_sha": payload.get("head_sha"),
            "tree_sha": payload.get("tree_sha"),
            "recorded_at": payload.get("recorded_at") or datetime.now(UTC).isoformat(),
            "evidence_digest": hashlib.sha256(
                json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    return current


def active_prs() -> list[dict[str, Any]]:
    rows = []
    for pr in pages("/pulls?state=open"):
        rows.append(
            {
                "number": pr["number"],
                "title": pr.get("title"),
                "draft": bool(pr.get("draft")),
                "head": pr.get("head", {}).get("ref"),
                "head_sha": pr.get("head", {}).get("sha"),
                "mergeable": pr.get("mergeable"),
            }
        )
    return rows


def sentinel(
    control: dict[str, Any],
    prs: list[dict[str, Any]],
    learning: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    recent_failures = sum(
        1 for event in learning.get("events", [])[-50:] if event.get("type") == "workflow_failure"
    )
    if recent_failures >= 5:
        findings.append(
            {
                "severity": "P2",
                "kind": "repeated-ci-failure",
                "count": recent_failures,
                "action": "REMEDIATE",
            }
        )
    if len(prs) > 4:
        findings.append(
            {
                "severity": "P3",
                "kind": "wip-overload",
                "count": len(prs),
                "action": "HOLD_NEW_WORK",
            }
        )
    if control.get("schema_version", 0) < 4:
        findings.append(
            {
                "severity": "P1",
                "kind": "control-plane-drift",
                "action": "REMEDIATE",
            }
        )
    return findings


def action_policy(
    prs: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(item["severity"] in {"P0", "P1"} for item in findings):
        return {"state": "REMEDIATE", "allow_new_slice": False}
    if prs:
        return {
            "state": "SERVICE_EXISTING_WORK",
            "allow_new_slice": False,
            "reason": "open PR ownership takes priority",
        }
    if any(item["action"] == "HOLD_NEW_WORK" for item in findings):
        return {"state": "HOLD", "allow_new_slice": False}
    return {"state": "EXECUTE_NEXT_SLICE", "allow_new_slice": True}


def dependency_graph(control: dict[str, Any]) -> dict[str, Any]:
    graph = load(
        DEPENDENCIES,
        {
            "schema_version": 1,
            "project": control.get("portfolio_aggregation", {}).get("project_key"),
            "edges": [],
        },
    )
    if graph.get("schema_version") != 1 or not isinstance(graph.get("edges"), list):
        raise SystemExit("portfolio-dependencies.json has invalid schema")
    return graph


def plan(output: Path, write_learning: bool, write_attestations: bool) -> int:
    control = load(CONTROL, {})
    learning = merged_learning(load(LEARNING, {"schema_version": 1, "events": []}))
    prs = active_prs()
    findings = sentinel(control, prs, learning)
    product_reality = harvest_product_reality(control)
    result = {
        "schema_version": 1,
        "repository": control.get("repository"),
        "generated_at": datetime.now(UTC).isoformat(),
        "action_policy": action_policy(prs, findings),
        "active_ownership": prs,
        "portfolio_dependencies": dependency_graph(control),
        "learning_candidates": learning.get("events", [])[-25:],
        "product_reality": product_reality,
        "sentinel_findings": sorted(
            findings,
            key=lambda item: -SEVERITY.get(item["severity"], 0),
        ),
        "specialist_dispatch": {
            "enabled": not bool(prs),
            "rule": (
                "one scheduler owns execution; lanes are reservations, "
                "not independent merge authorities"
            ),
            "lanes": [
                "implementation",
                "tests",
                "compatibility",
                "security",
                "docs",
                "product_reality_tooling",
            ],
        },
        "reserved_decisions": [
            "fundamental_product_direction",
            "major_unauthorized_architecture",
            "paid_service_or_recurring_cost",
            "license_change",
            "destructive_migration",
            "security_or_privacy_boundary_change",
            "credential_or_secret_problem",
            "release_or_publishing_authorization",
            "irreversible_action",
        ],
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if write_learning:
        LEARNING.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
    if write_attestations:
        ATTESTATIONS.write_text(json.dumps(product_reality, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


def validate() -> int:
    control = load(CONTROL, {})
    director = control.get("execution_director")
    errors = []
    if not isinstance(director, dict) or director.get("schema_version") != 1:
        errors.append("execution_director contract missing or invalid")
    if control.get("schema_version", 0) < 4:
        errors.append("execution director requires control-plane schema v4")
    try:
        dependency_graph(control)
    except SystemExit as exc:
        errors.append(str(exc))
    if errors:
        print(json.dumps({"status": "FAILED", "errors": errors}, indent=2))
        return 1
    print(json.dumps({"status": "GREEN", "repository": control.get("repository")}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Portfolio execution director.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("plan")
    build.add_argument("--output", default="execution-plan.json")
    build.add_argument("--write-learning", action="store_true")
    build.add_argument("--write-attestations", action="store_true")
    sub.add_parser("validate")
    args = parser.parse_args()
    if args.command == "plan":
        return plan(ROOT / args.output, args.write_learning, args.write_attestations)
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
