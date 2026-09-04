from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
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

FAIL_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
}
PASS_CONCLUSIONS = {"success", "neutral", "skipped"}
RESERVED_BRANCH_PREFIXES = ("agent/", "orchestrator/", "hotfix/", "fix/", "feat/")
SEVERITY = {"P0": 100, "P1": 80, "P2": 60, "P3": 40, "P4": 30, "P5": 20, "P6": 10}


def load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"


def github(path: str) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portfolio-execution-director",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
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


def wrapped_pages(path: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 51):
        payload = github(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
            raise SystemExit(f"Expected wrapped list '{key}' for {path}")
        batch = payload[key]
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise SystemExit(f"Pagination safety limit exceeded for {path}")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def workflow_learning() -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=14)
    events = []
    for run in wrapped_pages("/actions/runs?status=completed", "workflow_runs"):
        when = parse_time(run.get("created_at"))
        if when is None or when < cutoff:
            continue
        conclusion = str(run.get("conclusion") or "")
        if conclusion not in FAIL_CONCLUSIONS:
            continue
        events.append(
            {
                "type": "workflow_failure",
                "workflow": run.get("name"),
                "conclusion": conclusion,
                "head_sha": run.get("head_sha"),
                "run_id": run.get("id"),
                "recorded_at": run.get("created_at"),
            }
        )
    return events


def review_severity(body: str) -> str | None:
    match = re.search(r"\b(P[0-6])\s+Badge\b", body)
    return match.group(1) if match else None


def review_learning() -> list[dict[str, Any]]:
    events = []
    for pr in pages("/pulls?state=all&sort=updated&direction=desc"):
        number = int(pr["number"])
        for comment in pages(f"/pulls/{number}/comments"):
            severity = review_severity(str(comment.get("body") or ""))
            if severity is None:
                continue
            events.append(
                {
                    "type": "review_finding",
                    "severity": severity,
                    "pull_request": number,
                    "comment_id": comment.get("id"),
                    "path": comment.get("path"),
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
    events.sort(key=lambda event: str(event.get("recorded_at") or ""))
    return {
        "schema_version": 1,
        "events": events[-250:],
        "rule": "sanitized lessons only; never store secrets or private Product Reality payloads",
    }


def newest_inbox_records() -> dict[str, dict[str, Any]]:
    newest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    if not PRIVATE_INBOX.exists():
        return {}
    for path in PRIVATE_INBOX.glob("*.json"):
        payload = load(path, None)
        if not isinstance(payload, dict):
            continue
        lane = str(payload.get("lane") or "")
        when = parse_time(payload.get("recorded_at"))
        if not lane or when is None:
            continue
        prior = newest.get(lane)
        if prior is None or when > prior[0]:
            newest[lane] = (when, payload)
    return {lane: payload for lane, (_when, payload) in newest.items()}


def harvest_product_reality(control: dict[str, Any]) -> dict[str, Any]:
    repository = control["repository"]
    allowed = set(control.get("verification", {}).get("product_reality_lanes", []))
    current = load(
        ATTESTATIONS,
        {"schema_version": 1, "repository": repository, "lanes": {}},
    )
    if current.get("repository") != repository:
        raise SystemExit("Product Reality attestation repository mismatch")
    if not isinstance(current.get("lanes"), dict):
        raise SystemExit("Product Reality attestation lanes must be an object")

    current_tree = git_value("rev-parse", "HEAD^{tree}")
    lanes: dict[str, Any] = {}
    for lane in allowed:
        row = current["lanes"].get(lane)
        if not isinstance(row, dict):
            continue
        row = dict(row)
        if row.get("status") == "PASS" and row.get("tree_sha") != current_tree:
            row["status"] = "STALE"
        lanes[lane] = row

    for lane, payload in newest_inbox_records().items():
        if lane not in allowed:
            continue
        status = str(payload.get("status") or "").upper()
        refs = payload.get("evidence_refs") or []
        if status not in {"PASS", "FAIL", "PENDING", "BLOCKED"}:
            continue
        if status == "PASS" and not refs:
            continue
        tree_sha = payload.get("tree_sha")
        if status == "PASS" and tree_sha != current_tree:
            status = "STALE"
        lanes[lane] = {
            "status": status,
            "head_sha": payload.get("head_sha"),
            "tree_sha": tree_sha,
            "recorded_at": payload.get("recorded_at"),
            "evidence_digest": hashlib.sha256(
                json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }

    return {
        "schema_version": 1,
        "repository": repository,
        "lanes": lanes,
    }


def check_runs(head_sha: str) -> list[dict[str, Any]]:
    return wrapped_pages(f"/commits/{head_sha}/check-runs", "check_runs")


def classify_pr(pr: dict[str, Any]) -> dict[str, Any]:
    number = int(pr["number"])
    detail = github(f"/pulls/{number}")
    head_sha = str(detail.get("head", {}).get("sha") or "")
    checks = check_runs(head_sha)
    reviews = pages(f"/pulls/{number}/reviews")

    if detail.get("mergeable") is False:
        state = "CONFLICTED"
    elif any(str(check.get("conclusion") or "") in FAIL_CONCLUSIONS for check in checks):
        state = "FAILED"
    elif any(str(check.get("status") or "") != "completed" for check in checks):
        state = "PENDING"
    elif any(review.get("state") == "CHANGES_REQUESTED" for review in reviews):
        state = "BLOCKED"
    elif checks and all(str(check.get("conclusion") or "") in PASS_CONCLUSIONS for check in checks):
        state = "GREEN" if detail.get("mergeable") is True else "UNCERTAIN"
    else:
        state = "UNCERTAIN"

    return {
        "number": number,
        "title": detail.get("title"),
        "draft": bool(detail.get("draft")),
        "head": detail.get("head", {}).get("ref"),
        "head_sha": head_sha,
        "mergeable": detail.get("mergeable"),
        "classification": state,
    }


def open_priority_issues() -> list[dict[str, Any]]:
    rows = []
    for issue in pages("/issues?state=open"):
        if "pull_request" in issue:
            continue
        labels = {
            str(label.get("name") or "").upper()
            for label in issue.get("labels") or []
            if isinstance(label, dict)
        }
        priority = next((p for p in ("P0", "P1") if p in labels), None)
        if priority is None:
            title = str(issue.get("title") or "").lower()
            if "critical security" in title or "data loss" in title:
                priority = "P0"
        if priority:
            rows.append(
                {
                    "number": issue["number"],
                    "title": issue.get("title"),
                    "priority": priority,
                }
            )
    return rows


def recent_work_branches(open_pr_heads: set[str]) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(hours=12)
    rows = []
    for branch in pages("/branches"):
        name = str(branch.get("name") or "")
        if name in {"main", "master", "automation/status-reconcile"}:
            continue
        if name in open_pr_heads:
            continue
        if not name.startswith(RESERVED_BRANCH_PREFIXES):
            continue
        sha = str(branch.get("commit", {}).get("sha") or "")
        if not sha:
            continue
        commit = github(f"/commits/{sha}")
        when = parse_time(commit.get("commit", {}).get("committer", {}).get("date"))
        if when is None or when < cutoff:
            continue
        rows.append({"branch": name, "head_sha": sha, "updated_at": when.isoformat()})
    return rows


def active_ownership() -> dict[str, Any]:
    prs = [classify_pr(pr) for pr in pages("/pulls?state=open")]
    priority_issues = open_priority_issues()
    pr_heads = {str(pr.get("head") or "") for pr in prs}
    branches = recent_work_branches(pr_heads)
    return {
        "pull_requests": prs,
        "priority_issues": priority_issues,
        "recent_work_branches": branches,
    }


def recent_failure_count(learning: dict[str, Any]) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=14)
    count = 0
    for event in learning.get("events", []):
        if event.get("type") != "workflow_failure":
            continue
        when = parse_time(event.get("recorded_at"))
        if when is not None and when >= cutoff:
            count += 1
    return count


def sentinel(
    control: dict[str, Any],
    ownership: dict[str, Any],
    learning: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    failures = recent_failure_count(learning)
    if failures >= 5:
        findings.append(
            {
                "severity": "P2",
                "kind": "repeated-ci-failure",
                "count": failures,
                "action": "REMEDIATE",
            }
        )
    if len(ownership["pull_requests"]) > 4:
        findings.append(
            {
                "severity": "P3",
                "kind": "wip-overload",
                "count": len(ownership["pull_requests"]),
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
    ownership: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    if ownership["priority_issues"]:
        return {
            "state": "REMEDIATE",
            "allow_new_slice": False,
            "reason": "open P0/P1 issue",
        }
    if any(item.get("action") == "REMEDIATE" for item in findings):
        return {
            "state": "REMEDIATE",
            "allow_new_slice": False,
            "reason": "sentinel remediation required",
        }
    prs = ownership["pull_requests"]
    if prs:
        priority_order = {
            "FAILED": 0,
            "GREEN": 1,
            "BLOCKED": 2,
            "CONFLICTED": 3,
            "PENDING": 4,
            "UNCERTAIN": 5,
        }
        ordered = sorted(
            prs,
            key=lambda pr: (
                priority_order.get(str(pr["classification"]), 9),
                int(pr["number"]),
            ),
        )
        return {
            "state": "SERVICE_EXISTING_WORK",
            "allow_new_slice": False,
            "next_pull_request": ordered[0],
        }
    if ownership["recent_work_branches"]:
        return {
            "state": "SERVICE_EXISTING_WORK",
            "allow_new_slice": False,
            "reason": "recent attributable work branch",
        }
    if any(item.get("action") == "HOLD_NEW_WORK" for item in findings):
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


def plan(output: Path) -> int:
    control = load(CONTROL, {})
    learning = merged_learning(load(LEARNING, {"schema_version": 1, "events": []}))
    ownership = active_ownership()
    findings = sentinel(control, ownership, learning)
    policy = action_policy(ownership, findings)
    product_reality = harvest_product_reality(control)

    result = {
        "schema_version": 1,
        "repository": control.get("repository"),
        "generated_at": datetime.now(UTC).isoformat(),
        "action_policy": policy,
        "active_ownership": ownership,
        "portfolio_dependencies": dependency_graph(control),
        "learning_candidates": learning.get("events", [])[-25:],
        "product_reality": product_reality,
        "sentinel_findings": sorted(
            findings,
            key=lambda item: -SEVERITY.get(str(item["severity"]), 0),
        ),
        "specialist_dispatch": {
            "enabled": policy["state"] == "EXECUTE_NEXT_SLICE",
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
    print(output)
    return 0


def self_test() -> list[str]:
    errors = []
    remediation = action_policy(
        {"pull_requests": [], "priority_issues": [], "recent_work_branches": []},
        [{"severity": "P2", "action": "REMEDIATE"}],
    )
    if remediation["state"] != "REMEDIATE":
        errors.append("REMEDIATE sentinel action must block new work")
    priority = action_policy(
        {
            "pull_requests": [],
            "priority_issues": [{"number": 1, "priority": "P1"}],
            "recent_work_branches": [],
        },
        [],
    )
    if priority["state"] != "REMEDIATE":
        errors.append("P0/P1 issue must block new work")
    clean = action_policy(
        {"pull_requests": [], "priority_issues": [], "recent_work_branches": []},
        [],
    )
    if clean["state"] != "EXECUTE_NEXT_SLICE":
        errors.append("clean ownership state must permit next slice")
    return errors


def validate() -> int:
    control = load(CONTROL, {})
    director = control.get("execution_director")
    scheduler = control.get("scheduler_integration")
    errors = self_test()
    if not isinstance(director, dict) or director.get("schema_version") != 1:
        errors.append("execution_director contract missing or invalid")
    if control.get("schema_version", 0) < 4:
        errors.append("execution director requires control-plane schema v4")
    if not isinstance(scheduler, dict) or scheduler.get("schema_version") != 1:
        errors.append("scheduler_integration contract missing or invalid")
    else:
        expected_order = [
            "verify_live_github_state",
            "consume_execution_director",
            "consume_growth_engine",
            "consult_governing_roadmap",
        ]
        if scheduler.get("decision_order") != expected_order:
            errors.append("scheduler decision_order must preserve live-state-first execution")

        execution_plan = scheduler.get("execution_plan")
        if not isinstance(execution_plan, dict):
            errors.append("scheduler execution_plan contract is required")
        else:
            if execution_plan.get("workflow") != "Execution Director":
                errors.append(
                    "scheduler execution_plan workflow must be Execution Director"
                )
            if execution_plan.get("artifact") != "execution-plan":
                errors.append(
                    "scheduler execution_plan artifact must be execution-plan"
                )
            max_age = execution_plan.get("max_age_hours")
            if (
                not isinstance(max_age, (int, float))
                or max_age <= 0
                or max_age > 2
            ):
                errors.append(
                    "scheduler execution plan max_age_hours must be > 0 and <= 2"
                )
            if (
                execution_plan.get("require_default_branch_head_match")
                is not True
            ):
                errors.append(
                    "scheduler execution plan must require default-branch head match"
                )

        learning = scheduler.get("learning_persistence")
        if (
            not isinstance(learning, dict)
            or learning.get("destination")
            != "engineering/learning-memory.json"
        ):
            errors.append(
                "scheduler learning destination must be engineering/learning-memory.json"
            )

        dispatch = scheduler.get("specialist_dispatch")
        if not isinstance(dispatch, dict):
            errors.append("scheduler specialist_dispatch contract is required")
        else:
            if (
                dispatch.get("allowed_only_when_state")
                != "EXECUTE_NEXT_SLICE"
            ):
                errors.append(
                    "scheduler specialist dispatch must require EXECUTE_NEXT_SLICE"
                )
            if dispatch.get("reservation_required") is not True:
                errors.append("scheduler specialist dispatch must require reservations")
            if dispatch.get("one_scheduler_merge_authority") is not True:
                errors.append("scheduler must retain one merge authority")
            if (
                dispatch.get("max_substantial_new_slices_per_project_per_run")
                != 1
            ):
                errors.append(
                    "scheduler new-slice budget must remain one per project per run"
                )

        reality = scheduler.get("product_reality")
        if not isinstance(reality, dict):
            errors.append("scheduler Product Reality contract is required")
        else:
            if reality.get("use_sanitized_attestations_only") is not True:
                errors.append(
                    "scheduler must use sanitized Product Reality attestations only"
                )
            if reality.get("private_payloads_never_committed") is not True:
                errors.append(
                    "scheduler must never commit private Product Reality payloads"
                )
            if (
                reality.get("stale_pass_must_not_be_treated_as_verified")
                is not True
            ):
                errors.append(
                    "scheduler must reject stale Product Reality PASS evidence"
                )

        fallback = scheduler.get("fallback")
        if not isinstance(fallback, str) or "live" not in fallback.lower():
            errors.append("scheduler fallback must explicitly return to live evidence")
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
    sub.add_parser("validate")
    args = parser.parse_args()
    if args.command == "plan":
        return plan(ROOT / args.output)
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
