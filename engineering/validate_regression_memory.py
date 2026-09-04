from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "engineering" / "regression-memory.json"
    errors: list[str] = []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"REGRESSION_MEMORY_ERROR: cannot load {path.relative_to(root)}: {exc}", file=sys.stderr)
        return 1

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("repository") is None:
        errors.append("repository is required")

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be a list")
        entries = []

    ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("each entry must be an object")
            continue
        required = (
            "id",
            "symptom",
            "root_cause",
            "fix",
            "verification",
            "regression_protection",
            "residual_risk",
        )
        for key in required:
            if not entry.get(key):
                errors.append(f"entry missing {key}: {entry.get('id', '<unknown>')}")
        entry_id = entry.get("id")
        if isinstance(entry_id, str):
            ids.append(entry_id)
        protection = entry.get("regression_protection")
        if isinstance(protection, list):
            for item in protection:
                if isinstance(item, str) and ("/" in item or item.endswith((".py", ".yml", ".yaml", ".json"))):
                    if not (root / item).exists():
                        errors.append(f"regression protection path does not exist: {item}")

    if len(ids) != len(set(ids)):
        errors.append("regression-memory entry ids must be unique")

    if errors:
        for error in errors:
            print(f"REGRESSION_MEMORY_ERROR: {error}", file=sys.stderr)
        return 1

    print(f"regression memory valid: {len(entries)} recorded incident(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
