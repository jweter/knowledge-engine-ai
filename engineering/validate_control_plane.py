from __future__ import annotations
import json, os, sys
from pathlib import Path

REQUIRED_TOP = {
    "schema_version","portfolio_project","repository","repository_role",
    "source_of_truth","authoritative_documents","definition_of_done",
    "invariants","verification","work_ownership","regression_memory",
    "readiness_scoring","continuation",
}

def fail(messages: list[str]) -> int:
    for msg in messages:
        print(f"CONTROL_PLANE_ERROR: {msg}", file=sys.stderr)
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
    if missing: errors.append("missing top-level keys: " + ", ".join(missing))
    if data.get("schema_version") != 2: errors.append("schema_version must be 2")
    repo = data.get("repository")
    if not isinstance(repo, str) or "/" not in repo: errors.append("repository must be owner/name")
    github_repo = os.getenv("GITHUB_REPOSITORY")
    if github_repo and repo != github_repo: errors.append(f"repository {repo!r} does not match GITHUB_REPOSITORY {github_repo!r}")
    docs = data.get("authoritative_documents")
    if not isinstance(docs, list) or not docs: errors.append("authoritative_documents must be a non-empty list")
    else:
        for item in docs:
            if not isinstance(item, str) or not item:
                errors.append("authoritative_documents entries must be non-empty strings"); continue
            target=(root/item).resolve()
            try: target.relative_to(root.resolve())
            except ValueError: errors.append(f"authoritative document escapes repository: {item}"); continue
            if not target.is_file(): errors.append(f"authoritative document does not exist: {item}")
    invariants=data.get("invariants")
    if not isinstance(invariants,list) or not invariants or len(invariants)!=len(set(invariants)): errors.append("invariants must be a non-empty unique list")
    verification=data.get("verification")
    if not isinstance(verification,dict): errors.append("verification must be an object")
    else:
        for key in ("automated_lanes","product_reality_lanes"):
            value=verification.get(key)
            if not isinstance(value,list) or not value: errors.append(f"verification.{key} must be non-empty")
        executable=verification.get("executable_lanes")
        if not isinstance(executable,list) or not executable: errors.append("verification.executable_lanes must be non-empty")
        else:
            ids=[]
            for lane in executable:
                if not isinstance(lane,dict): errors.append("each executable lane must be an object"); continue
                lane_id=lane.get("id"); steps=lane.get("steps")
                if not isinstance(lane_id,str) or not lane_id: errors.append("each executable lane requires a non-empty id")
                else: ids.append(lane_id)
                if not isinstance(steps,list) or not steps: errors.append(f"executable lane {lane_id!r} requires non-empty steps")
                else:
                    for step in steps:
                        if not isinstance(step,list) or not step or not all(isinstance(v,str) and v for v in step):
                            errors.append(f"executable lane {lane_id!r} contains an invalid argv step")
            if len(ids)!=len(set(ids)): errors.append("verification.executable_lanes ids must be unique")
    scoring=data.get("readiness_scoring")
    if not isinstance(scoring,dict) or scoring.get("prohibit_guessed_percent_complete") is not True:
        errors.append("readiness_scoring must prohibit guessed percent complete")
    if errors: return fail(errors)
    print(f"control-plane contract valid for {repo}")
    return 0
if __name__=="__main__": raise SystemExit(main())
