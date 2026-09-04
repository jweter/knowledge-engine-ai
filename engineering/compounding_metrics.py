from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

UNKNOWN = "UNKNOWN"
AUTOMATION_PREFIXES = ("agent/", "orchestrator/", "hotfix/")
FAIL_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
}
DEPENDENCY_PATTERN = re.compile(
    r"(?:blocked by|depends on|requires)\s+#(\d+)",
    re.IGNORECASE,
)


def github_json(path: str) -> Any:
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
            "User-Agent": "engineering-compounding-metrics",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def github_pages(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 21):
        batch = github_json(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise SystemExit(f"Expected list response for {path}")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise SystemExit(f"Pagination safety limit exceeded for {path}")


def github_wrapped_pages(path: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 21):
        payload = github_json(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
            raise SystemExit(f"Expected wrapped list '{key}' for {path}")
        batch = payload[key]
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise SystemExit(f"Pagination safety limit exceeded for {path}")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def safe_ratio(numerator: Any, denominator: Any) -> float | str:
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, (int, float))
        or not isinstance(denominator, (int, float))
        or denominator <= 0
    ):
        return UNKNOWN
    return round(numerator / denominator, 4)


def merged_in_window(
    pulls: list[dict[str, Any]], start: datetime, end: datetime
) -> list[dict[str, Any]]:
    merged = []
    for pull in pulls:
        merged_at = parse_time(pull.get("merged_at"))
        if merged_at is not None and start <= merged_at < end:
            merged.append(pull)
    return merged


def automation_attributed(pull: dict[str, Any]) -> bool:
    head = pull.get("head") or {}
    ref = str(head.get("ref") or "")
    user = pull.get("user") or {}
    login = str(user.get("login") or "")
    user_type = str(user.get("type") or "")
    return (
        ref.startswith(AUTOMATION_PREFIXES)
        or user_type.lower() == "bot"
        or login.endswith("[bot]")
    )


def is_human_actor(user: Any) -> bool:
    if not isinstance(user, dict):
        return False
    login = str(user.get("login") or "")
    user_type = str(user.get("type") or "")
    return bool(login) and user_type.lower() != "bot" and not login.endswith("[bot]")


def pull_has_human_intervention(
    pull_number: int,
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> bool:
    _ = pull_number
    return any(is_human_actor(row.get("user")) for row in reviews + comments)


def repeat_failure_rate(
    runs: list[dict[str, Any]], start: datetime, end: datetime
) -> float | str:
    failures = []
    for run in runs:
        created_at = parse_time(run.get("created_at"))
        conclusion = str(run.get("conclusion") or "")
        if (
            created_at is not None
            and start <= created_at < end
            and conclusion in FAIL_CONCLUSIONS
        ):
            failures.append(str(run.get("name") or "UNKNOWN_WORKFLOW"))
    if not failures:
        return UNKNOWN
    repeats = len(failures) - len(set(failures))
    return safe_ratio(repeats, len(failures))


def dependency_unlock_rate(
    issues: list[dict[str, Any]], start: datetime, end: datetime, merged_prs: int
) -> float | str:
    if merged_prs <= 0:
        return UNKNOWN
    by_number = {
        int(issue["number"]): issue
        for issue in issues
        if "pull_request" not in issue and issue.get("number") is not None
    }
    edges: set[tuple[int, int]] = set()
    for issue in by_number.values():
        source = int(issue["number"])
        body = str(issue.get("body") or "")
        for match in DEPENDENCY_PATTERN.finditer(body):
            target = int(match.group(1))
            if target in by_number and target != source:
                edges.add((source, target))

    unlocked_edges = 0
    for _source, target in edges:
        closed_at = parse_time(by_number[target].get("closed_at"))
        if closed_at is not None and start <= closed_at < end:
            unlocked_edges += 1
    return safe_ratio(unlocked_edges, merged_prs)


def window_metrics(
    pulls: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    intervention: dict[int, bool],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    merged = merged_in_window(pulls, start, end)
    cycle_hours = []
    for pull in merged:
        merged_at = parse_time(pull.get("merged_at"))
        created_at = parse_time(pull.get("created_at"))
        if merged_at is not None and created_at is not None:
            cycle_hours.append((merged_at - created_at).total_seconds() / 3600)

    autonomous = sum(1 for pull in merged if automation_attributed(pull))
    human_touched = sum(
        1
        for pull in merged
        if intervention.get(int(pull.get("number") or 0), False)
    )
    merged_count = len(merged)

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "merged_prs": merged_count,
        "median_pr_cycle_hours": (
            round(statistics.median(cycle_hours), 2) if cycle_hours else UNKNOWN
        ),
        "sample_size": merged_count,
        "repeat_failure_rate": repeat_failure_rate(runs, start, end),
        "autonomous_completion_rate": safe_ratio(autonomous, merged_count),
        "dependency_unlock_rate": dependency_unlock_rate(
            issues, start, end, merged_count
        ),
        "human_intervention_rate": safe_ratio(human_touched, merged_count),
    }


def intervention_evidence(
    pulls: list[dict[str, Any]], earliest: datetime, latest: datetime
) -> dict[int, bool]:
    evidence: dict[int, bool] = {}
    for pull in merged_in_window(pulls, earliest, latest):
        number = int(pull["number"])
        reviews = github_pages(f"/pulls/{number}/reviews")
        comments = github_pages(f"/issues/{number}/comments")
        evidence[number] = pull_has_human_intervention(number, reviews, comments)
    return evidence


def factor(current: Any, previous: Any, lower_is_better: bool = False) -> float | str:
    if lower_is_better:
        return safe_ratio(previous, current)
    return safe_ratio(current, previous)


def build_report(days: int, now: datetime) -> dict[str, Any]:
    pulls = github_pages("/pulls?state=closed&sort=updated&direction=desc")
    runs = github_wrapped_pages("/actions/runs?status=completed", "workflow_runs")
    issues = github_pages("/issues?state=all&sort=updated&direction=desc")

    earliest = now - timedelta(days=3 * days)
    intervention = intervention_evidence(pulls, earliest, now)

    current = window_metrics(
        pulls, runs, issues, intervention, now - timedelta(days=days), now
    )
    previous = window_metrics(
        pulls,
        runs,
        issues,
        intervention,
        now - timedelta(days=2 * days),
        now - timedelta(days=days),
    )
    older = window_metrics(
        pulls,
        runs,
        issues,
        intervention,
        now - timedelta(days=3 * days),
        now - timedelta(days=2 * days),
    )

    throughput_factor = factor(current["merged_prs"], previous["merged_prs"])
    prior_throughput_factor = factor(previous["merged_prs"], older["merged_prs"])
    cycle_time_factor = factor(
        current["median_pr_cycle_hours"],
        previous["median_pr_cycle_hours"],
        lower_is_better=True,
    )
    repeat_failure_factor = factor(
        current["repeat_failure_rate"],
        previous["repeat_failure_rate"],
        lower_is_better=True,
    )
    autonomous_completion_factor = factor(
        current["autonomous_completion_rate"],
        previous["autonomous_completion_rate"],
    )
    dependency_unlock_factor = factor(
        current["dependency_unlock_rate"],
        previous["dependency_unlock_rate"],
    )
    human_intervention_factor = factor(
        current["human_intervention_rate"],
        previous["human_intervention_rate"],
        lower_is_better=True,
    )

    emf = UNKNOWN
    if isinstance(throughput_factor, float) and isinstance(cycle_time_factor, float):
        emf = round(throughput_factor * cycle_time_factor, 4)

    compounding_rate = UNKNOWN
    if isinstance(throughput_factor, float) and isinstance(prior_throughput_factor, float):
        compounding_rate = safe_ratio(throughput_factor, prior_throughput_factor)
        if isinstance(compounding_rate, float):
            compounding_rate = round(compounding_rate - 1.0, 4)

    return {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "window_days": days,
        "windows": {"current": current, "previous": previous, "older": older},
        "evidence_derived": {
            "throughput_factor": throughput_factor,
            "cycle_time_factor": cycle_time_factor,
            "engineering_multiplication_factor": emf,
            "compounding_rate": compounding_rate,
            "repeat_failure_factor": repeat_failure_factor,
            "autonomous_completion_factor": autonomous_completion_factor,
            "dependency_unlock_factor": dependency_unlock_factor,
            "human_intervention_factor": human_intervention_factor,
        },
        "methodology": {
            "repeat_failure_rate": (
                "share of failing workflow events that repeat a workflow signature "
                "already failing in the same window"
            ),
            "autonomous_completion_rate": (
                "proxy: share of merged PRs attributable to agent/, orchestrator/, "
                "hotfix/ branches or bot authors; this does not prove zero human input"
            ),
            "dependency_unlock_rate": (
                "explicit blocked-by/depends-on/requires dependency edges whose "
                "blocking issue closed in the window, divided by merged PR count"
            ),
            "human_intervention_rate": (
                "share of merged PRs with observable non-bot review or issue-comment "
                "activity"
            ),
        },
        "interpretation": (
            "These are descriptive GitHub-history metrics, not proof of exponential "
            "growth. Compounding requires sustained positive evidence across multiple "
            "windows. UNKNOWN is mandatory when evidence is insufficient."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.window_days <= 0:
        raise SystemExit("--window-days must be positive")
    report = build_report(args.window_days, datetime.now(UTC))
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
