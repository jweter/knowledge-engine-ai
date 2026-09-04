from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "engineering" / "control-plane.json"
LEARNING_MEMORY = ROOT / "engineering" / "learning-memory.json"
REGRESSION_MEMORY = ROOT / "engineering" / "regression-memory.json"
PRODUCT_REALITY_ATTESTATIONS = ROOT / "engineering" / "product-reality-attestations.json"

PRIORITY_WEIGHTS = {
    "P0": 100,
    "P1": 80,
    "P2": 60,
    "P3": 40,
    "P4": 30,
    "P5": 20,
    "P6": 10,
}
SPECIALIST_LANES = (
    "implementation",
    "tests",
    "compatibility",
    "docs",
    "security",
    "product_reality_tooling",
)


@dataclass(frozen=True)
class Candidate:
    number: int
    title: str
    url: str
    labels: tuple[str, ...]
    milestone: str | None
    score: int
    reasons: tuple[str, ...]
    blocked: bool
    product_reality_dependent: bool


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_control() -> dict[str, Any]:
    return load_json(CONTROL, {})


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
            "User-Agent": "growth-control-plane",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def github_pages(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 101):
        batch = github_json(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise SystemExit(f"Expected list response for {path}")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise SystemExit(f"Pagination safety limit exceeded for {path}")


def normalize_labels(item: dict[str, Any]) -> tuple[str, ...]:
    labels = []
    for label in item.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else str(label)
        if name:
            labels.append(str(name))
    return tuple(sorted(labels))


def classify_priority(labels: tuple[str, ...], title: str) -> str:
    upper = {label.upper() for label in labels}
    for priority in PRIORITY_WEIGHTS:
        if priority in upper:
            return priority
    lowered = title.lower()
    if "security" in lowered or "data loss" in lowered or "critical" in lowered:
        return "P0"
    if "bug" in lowered or "failure" in lowered or "broken" in lowered:
        return "P1"
    return "P5"


def is_blocked(labels: tuple[str, ...], body: str) -> bool:
    label_text = " ".join(labels).lower()
    body_text = body.lower()
    return (
        "blocked" in label_text
        or "waiting" in label_text
        or "blocked by" in body_text
    )


def is_product_reality_dependent(
    labels: tuple[str, ...],
    body: str,
    title: str,
) -> bool:
    text = " ".join(labels) + " " + body + " " + title
    lowered = text.lower()
    keywords = (
        "product reality",
        "playtest",
        "unreal",
        "real game",
        "packaged",
        "human review",
        "listening",
        "visual check",
    )
    return any(keyword in lowered for keyword in keywords)


def score_issue(item: dict[str, Any]) -> Candidate:
    labels = normalize_labels(item)
    title = str(item.get("title") or "")
    body = str(item.get("body") or "")
    priority = classify_priority(labels, title)
    score = PRIORITY_WEIGHTS[priority]
    reasons = [priority]

    milestone = None
    raw_milestone = item.get("milestone")
    if isinstance(raw_milestone, dict):
        milestone = raw_milestone.get("title")
        if milestone:
            score += 12
            reasons.append("active milestone")

    blocked = is_blocked(labels, body)
    if blocked:
        score -= 50
        reasons.append("blocked")

    product_reality_dependent = is_product_reality_dependent(labels, body, title)
    if product_reality_dependent:
        score -= 8
        reasons.append("Product Reality dependent")
    else:
        score += 10
        reasons.append("independent engineering")

    lowered_labels = {label.lower() for label in labels}
    if any("security" in label for label in lowered_labels):
        score += 20
        reasons.append("security")
    if any("bug" in label for label in lowered_labels):
        score += 12
        reasons.append("bug")
    if any(
        "small" in label or "size:s" in label
        for label in lowered_labels
    ):
        score += 8
        reasons.append("small/reversible")
    if any(
        "dependency" in label or "blocker" in label
        for label in lowered_labels
    ):
        score += 15
        reasons.append("dependency unlock")

    return Candidate(
        number=int(item["number"]),
        title=title,
        url=str(item.get("html_url") or ""),
        labels=labels,
        milestone=milestone,
        score=score,
        reasons=tuple(reasons),
        blocked=blocked,
        product_reality_dependent=product_reality_dependent,
    )


def candidate_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "issue": candidate.number,
        "title": candidate.title,
        "url": candidate.url,
        "labels": list(candidate.labels),
        "milestone": candidate.milestone,
        "score": candidate.score,
        "reasons": list(candidate.reasons),
        "blocked": candidate.blocked,
        "product_reality_dependent": candidate.product_reality_dependent,
    }


def extract_dependencies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_numbers = {int(item["number"]) for item in items}
    edges: set[tuple[int, int]] = set()
    pattern = re.compile(
        r"(?:blocked by|depends on|requires)\s+#(\d+)",
        re.IGNORECASE,
    )
    for item in items:
        source = int(item["number"])
        body = str(item.get("body") or "")
        for match in pattern.finditer(body):
            target = int(match.group(1))
            if target in issue_numbers and target != source:
                edges.add((source, target))
    incoming: dict[int, int] = {number: 0 for number in issue_numbers}
    for _source, target in edges:
        incoming[target] = incoming.get(target, 0) + 1
    return [
        {
            "blocked_issue": source,
            "dependency_issue": target,
            "unlock_weight": incoming.get(target, 0),
        }
        for source, target in sorted(edges)
    ]


def path_component(path: str) -> str:
    normalized = path.strip("/")
    if not normalized:
        return "."
    parts = normalized.split("/")
    return "/".join(parts[:2]) if len(parts) > 1 else parts[0]


def active_ownership(open_prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ownership = []
    for pr in open_prs:
        number = int(pr["number"])
        files = github_pages(f"/pulls/{number}/files")
        paths = sorted(
            str(file.get("filename"))
            for file in files
            if file.get("filename")
        )
        components = sorted({path_component(path) for path in paths})
        ownership.append(
            {
                "number": number,
                "title": pr.get("title"),
                "head": pr.get("head", {}).get("ref"),
                "draft": bool(pr.get("draft")),
                "paths": paths,
                "components": components,
            }
        )
    return ownership


def issue_area(candidate: Candidate) -> str | None:
    for label in candidate.labels:
        if label.lower().startswith("area:"):
            return label.split(":", 1)[1].strip()
    return None


def assign_specialist_lanes(
    candidates: list[Candidate],
    ownership: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    occupied_components = {
        component
        for owner in ownership
        for component in owner.get("components", [])
    }
    assignments: list[dict[str, Any]] = []
    used_lanes: set[str] = set()
    for candidate in candidates:
        if candidate.blocked:
            continue
        title = candidate.title.lower()
        if "security" in title:
            lane = "security"
        elif "test" in title or "regression" in title:
            lane = "tests"
        elif "doc" in title:
            lane = "docs"
        elif candidate.product_reality_dependent:
            lane = "product_reality_tooling"
        elif "api" in title or "schema" in title or "contract" in title:
            lane = "compatibility"
        else:
            lane = "implementation"
        if lane in used_lanes:
            continue

        area = issue_area(candidate)
        conflict = bool(area and area in occupied_components)
        assignments.append(
            {
                "lane": lane,
                "issue": candidate.number,
                "title": candidate.title,
                "reservation": f"issue:{candidate.number}",
                "area": area,
                "conflicted": conflict,
                "conflict_rule": (
                    "do not overlap active PR paths/components or another specialist lane"
                ),
            }
        )
        used_lanes.add(lane)
        if len(assignments) >= len(SPECIALIST_LANES):
            break
    return assignments


def sentinel_findings(
    control: dict[str, Any],
    open_prs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if control.get("schema_version", 0) < 4:
        findings.append(
            {
                "severity": "P2",
                "kind": "control-plane-drift",
                "message": (
                    "control-plane schema is older than v4; "
                    "promotion/preflight contract may be incomplete"
                ),
            }
        )
    preflight = control.get("preflight")
    if not isinstance(preflight, dict) or not preflight.get("required_before_pr"):
        findings.append(
            {
                "severity": "P1",
                "kind": "preflight-gap",
                "message": "canonical required-before-PR preflight is not declared",
            }
        )
    if len(open_prs) > 4:
        findings.append(
            {
                "severity": "P3",
                "kind": "work-in-progress",
                "message": (
                    "more than four open PRs increases ownership/conflict risk"
                ),
            }
        )
    if not control.get("growth_engine"):
        findings.append(
            {
                "severity": "P2",
                "kind": "growth-contract-gap",
                "message": "growth engine is not governed by control-plane manifest",
            }
        )
    return findings


def learning_summary(
    memory: dict[str, Any],
    regression_memory: Any,
) -> dict[str, Any]:
    events = memory.get("events", []) if isinstance(memory, dict) else []
    event_types: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("type") or "unknown")
        event_types[event_type] = event_types.get(event_type, 0) + 1
    regression_count = (
        len(regression_memory)
        if isinstance(regression_memory, list)
        else 0
    )
    return {
        "event_count": len(events),
        "event_types": event_types,
        "regression_memory_entries": regression_count,
        "rule": (
            "learning evidence informs ranking but never overrides security, CI, "
            "ownership, or Product Reality gates"
        ),
    }


def cross_repo_graph(control: dict[str, Any]) -> list[dict[str, str]]:
    edges = []
    repository = str(control.get("repository") or "")
    for authority in control.get("cross_repo_authorities", []):
        if not isinstance(authority, dict):
            continue
        target = authority.get("repository")
        if not target:
            continue
        edges.append(
            {
                "from_repository": repository,
                "to_repository": str(target),
                "path": str(authority.get("path") or ""),
                "purpose": str(authority.get("purpose") or ""),
            }
        )
    return edges


def load_attestations(repository: str) -> dict[str, Any]:
    default = {
        "schema_version": 1,
        "repository": repository,
        "lanes": {},
    }
    payload = load_json(PRODUCT_REALITY_ATTESTATIONS, default)
    if payload.get("schema_version") != 1:
        raise SystemExit("Product Reality attestation schema must be 1")
    if payload.get("repository") != repository:
        raise SystemExit("Product Reality attestation repository mismatch")
    if not isinstance(payload.get("lanes"), dict):
        raise SystemExit("Product Reality attestation lanes must be an object")
    return payload


def ingest_product_reality(args: argparse.Namespace) -> int:
    control = load_control()
    repository = str(control.get("repository") or "")
    allowed = set(
        control.get("verification", {}).get("product_reality_lanes", [])
    )
    payload = load_json(Path(args.input), None)
    if not isinstance(payload, dict):
        raise SystemExit("Product Reality input must be a JSON object")

    lane = str(payload.get("lane") or "")
    status = str(payload.get("status") or "").upper()
    if lane not in allowed:
        raise SystemExit(f"Unknown Product Reality lane: {lane}")
    if status not in {"PASS", "FAIL", "PENDING", "BLOCKED"}:
        raise SystemExit("Product Reality status is invalid")
    if status == "PASS" and not payload.get("evidence_refs"):
        raise SystemExit("PASS requires evidence_refs")

    attestation = {
        "status": status,
        "head_sha": payload.get("head_sha"),
        "tree_sha": payload.get("tree_sha"),
        "recorded_at": payload.get("recorded_at")
        or datetime.now(UTC).isoformat(),
        "evidence_digest": hashlib.sha256(
            json.dumps(
                payload.get("evidence_refs") or [],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    attestations = load_attestations(repository)
    attestations["lanes"][lane] = attestation
    PRODUCT_REALITY_ATTESTATIONS.write_text(
        json.dumps(attestations, indent=2) + "\n",
        encoding="utf-8",
    )
    print(PRODUCT_REALITY_ATTESTATIONS)
    return 0


def snapshot(output: Path) -> int:
    control = load_control()
    issues = [
        item
        for item in github_pages("/issues?state=open")
        if "pull_request" not in item
    ]
    open_prs = github_pages("/pulls?state=open")
    ownership = active_ownership(open_prs)
    candidates = sorted(
        (score_issue(item) for item in issues),
        key=lambda candidate: (-candidate.score, candidate.number),
    )
    dependencies = extract_dependencies(issues)
    unlock_counts: dict[int, int] = {}
    for edge in dependencies:
        dependency = int(edge["dependency_issue"])
        unlock_counts[dependency] = unlock_counts.get(dependency, 0) + 1

    ranked = []
    for candidate in candidates:
        row = candidate_dict(candidate)
        row["downstream_unlocks"] = unlock_counts.get(candidate.number, 0)
        row["score"] += 10 * row["downstream_unlocks"]
        ranked.append(row)
    ranked.sort(key=lambda row: (-row["score"], row["issue"]))

    memory = load_json(
        LEARNING_MEMORY,
        {"schema_version": 1, "events": []},
    )
    regression_memory = load_json(REGRESSION_MEMORY, [])
    repository = str(control.get("repository") or "")
    attestations = load_attestations(repository)

    result = {
        "schema_version": 1,
        "repository": repository,
        "generated_at": datetime.now(UTC).isoformat(),
        "learning": learning_summary(memory, regression_memory),
        "ranked_next_slices": ranked[:10],
        "dependency_graph": dependencies,
        "cross_repo_dependency_graph": cross_repo_graph(control),
        "specialist_lane_plan": assign_specialist_lanes(
            candidates,
            ownership,
        ),
        "active_ownership": ownership,
        "product_reality_attestations": attestations,
        "readiness_sentinel": sentinel_findings(control, open_prs),
        "guardrails": {
            "max_substantial_new_slices_per_project": 1,
            "never_auto_accept_product_reality": True,
            "never_bypass_preflight_or_required_ci": True,
            "never_duplicate_active_ownership": True,
            "recommendations_are_not_merge_authority": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


def record_learning_event(args: argparse.Namespace) -> int:
    memory = load_json(
        LEARNING_MEMORY,
        {"schema_version": 1, "events": []},
    )
    if memory.get("schema_version") != 1:
        raise SystemExit("learning-memory.json schema must be 1")
    if not isinstance(memory.get("events"), list):
        raise SystemExit("learning-memory.json events must be a list")

    normalized = {
        "type": args.type,
        "repository": load_control().get("repository"),
        "summary": args.summary,
        "root_cause": args.root_cause,
        "successful_pattern": args.successful_pattern,
        "verification": args.verification,
        "residual_risk": args.residual_risk,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if any(
        event.get("fingerprint") == fingerprint
        for event in memory["events"]
    ):
        print("duplicate learning event ignored")
        return 0
    normalized["fingerprint"] = fingerprint
    normalized["recorded_at"] = datetime.now(UTC).isoformat()
    memory["events"].append(normalized)
    LEARNING_MEMORY.write_text(
        json.dumps(memory, indent=2) + "\n",
        encoding="utf-8",
    )
    print(fingerprint)
    return 0


def validate() -> int:
    control = load_control()
    growth = control.get("growth_engine")
    errors = []
    if not isinstance(growth, dict):
        errors.append("control-plane growth_engine contract is missing")
    memory = load_json(LEARNING_MEMORY, None)
    if not isinstance(memory, dict) or memory.get("schema_version") != 1:
        errors.append("learning-memory.json has invalid schema")
    elif not isinstance(memory.get("events"), list):
        errors.append("learning-memory.json events must be a list")

    if PRODUCT_REALITY_ATTESTATIONS.exists():
        try:
            load_attestations(str(control.get("repository") or ""))
        except SystemExit as exc:
            errors.append(str(exc))

    if errors:
        print(json.dumps({"status": "FAILED", "errors": errors}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "GREEN",
                "repository": control.get("repository"),
                "growth_schema_version": growth.get("schema_version"),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evidence-driven exponential-growth control plane."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot")
    snap.add_argument("--output", default="growth-snapshot.json")

    learn = sub.add_parser("record-learning")
    learn.add_argument("--type", required=True)
    learn.add_argument("--summary", required=True)
    learn.add_argument("--root-cause")
    learn.add_argument("--successful-pattern")
    learn.add_argument("--verification")
    learn.add_argument("--residual-risk")

    intake = sub.add_parser("ingest-product-reality")
    intake.add_argument("--input", required=True)

    sub.add_parser("validate")

    args = parser.parse_args()
    if args.command == "snapshot":
        return snapshot(ROOT / args.output)
    if args.command == "record-learning":
        return record_learning_event(args)
    if args.command == "ingest-product-reality":
        return ingest_product_reality(args)
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
