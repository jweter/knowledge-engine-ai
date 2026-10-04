from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "engineering" / "control-plane.json"
LOCAL_MEMORY = ROOT / "engineering" / "learning-memory.json"
DEFAULT_ENV = "AZATHOTH_SHARED_MEMORY_DIR"
DEFAULT_RELATIVE_ROOT = Path(".azathoth") / "shared-memory"
SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(password|api[_-]?key|secret|token)\s*[:=]\s*[^\s]+"),
]
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./-]{1,}")


def shared_root() -> Path:
    configured = os.environ.get(DEFAULT_ENV)
    return Path(configured).expanduser() if configured else Path.home() / DEFAULT_RELATIVE_ROOT


def repository_identity() -> str:
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    return str(control.get("development_repository") or control.get("repository") or "").strip()


def _contains_secret(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True)
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def load_local_memory() -> dict[str, Any]:
    payload = json.loads(LOCAL_MEMORY.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("events"), list):
        raise ValueError("learning-memory.json must be schema_version 1 with an events list")
    if _contains_secret(payload):
        raise ValueError("learning memory appears to contain secret material")
    return payload


def verified_events(memory: dict[str, Any]) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    repo = repository_identity()
    for raw in memory["events"]:
        if not isinstance(raw, dict):
            continue
        verification = raw.get("verification")
        if not isinstance(verification, str) or not verification.strip():
            continue
        event = dict(raw)
        event["repository"] = str(event.get("repository") or repo)
        event["evidence_state"] = "VERIFIED"
        if _contains_secret(event):
            continue
        verified.append(event)
    return verified


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}.", suffix=".tmp"
    ) as handle:
        handle.write(content)
        temp = Path(handle.name)
    os.replace(temp, path)


def publish(root: Path | None = None) -> dict[str, Any]:
    destination = (root or shared_root()).expanduser()
    repo = repository_identity()
    payload = {
        "schema_version": 1,
        "kind": "azathoth-repository-learning-snapshot",
        "repository": repo,
        "events": verified_events(load_local_memory()),
    }
    safe_name = repo.replace("/", "__")
    path = destination / "repos" / f"{safe_name}.json"
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {
        "state": "PUBLISHED",
        "repository": repo,
        "verified_event_count": len(payload["events"]),
        "path": str(path),
    }


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(value.lower()) if len(token) >= 3}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def query(
    terms: list[str], root: Path | None = None, repository: str | None = None, limit: int = 8
) -> dict[str, Any]:
    destination = (root or shared_root()).expanduser()
    target_repo = repository or repository_identity()
    wanted = _tokens(" ".join(terms))
    candidates: list[dict[str, Any]] = []

    central = _load_json(destination / "memory.json")
    if isinstance(central, dict):
        for lesson in central.get("entries", []):
            if not isinstance(lesson, dict) or lesson.get("evidence_state") != "VERIFIED":
                continue
            if target_repo and lesson.get("repository") != target_repo:
                continue
            text = " ".join(
                str(lesson.get(k, ""))
                for k in (
                    "symptom",
                    "root_cause",
                    "fix",
                    "verification",
                    "regression_protection",
                    "residual_risk",
                )
            )
            overlap = sorted(wanted & _tokens(text))
            if wanted and not overlap:
                continue
            candidates.append(
                {
                    "source": "portfolio",
                    "score": 50 + 10 * len(overlap),
                    "match_terms": overlap,
                    "record": lesson,
                }
            )

    repo_dir = destination / "repos"
    if repo_dir.exists():
        for path in sorted(repo_dir.glob("*.json")):
            snapshot = _load_json(path)
            if (
                not isinstance(snapshot, dict)
                or snapshot.get("kind") != "azathoth-repository-learning-snapshot"
            ):
                continue
            if target_repo and snapshot.get("repository") != target_repo:
                continue
            for event in snapshot.get("events", []):
                if not isinstance(event, dict) or event.get("evidence_state") != "VERIFIED":
                    continue
                text = " ".join(str(v) for v in event.values() if isinstance(v, (str, int, float)))
                overlap = sorted(wanted & _tokens(text))
                if wanted and not overlap:
                    continue
                candidates.append(
                    {
                        "source": "repository",
                        "score": 60 + 10 * len(overlap),
                        "match_terms": overlap,
                        "record": event,
                    }
                )

    candidates.sort(key=lambda item: (-item["score"], json.dumps(item["record"], sort_keys=True)))
    return {
        "state": "MATCHES" if candidates else "NO_MATCH",
        "repository": target_repo,
        "results": candidates[:limit],
    }


def self_test() -> int:
    memory = load_local_memory()
    if not isinstance(verified_events(memory), list):
        raise ValueError("verified event projection failed")
    with tempfile.TemporaryDirectory(prefix="iron-memory-") as temp:
        root = Path(temp)
        result = publish(root)
        if result["state"] != "PUBLISHED":
            raise ValueError("publish failed")
        query([], root=root)
    print("IRON MEMORY BRIDGE: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("--root", type=Path, default=None)
    query_parser = sub.add_parser("query")
    query_parser.add_argument("--root", type=Path, default=None)
    query_parser.add_argument("--repository", default=None)
    query_parser.add_argument("--term", action="append", dest="terms", default=[])
    query_parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    if args.command == "validate":
        return self_test()
    if args.command == "publish":
        print(json.dumps(publish(args.root), indent=2, sort_keys=True))
        return 0
    print(
        json.dumps(
            query(args.terms, args.root, args.repository, args.limit), indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
