from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
def main() -> int:
    p=argparse.ArgumentParser(description="Run executable control-plane verification lanes.")
    p.add_argument("--lane",action="append",default=[])
    args=p.parse_args(); root=Path(__file__).resolve().parents[1]
    data=json.loads((root/"engineering"/"control-plane.json").read_text(encoding="utf-8"))
    lanes=data["verification"]["executable_lanes"]; wanted=set(args.lane)
    selected=[x for x in lanes if not wanted or x["id"] in wanted]
    missing=wanted-{x["id"] for x in selected}
    if missing: print("unknown lane(s): "+", ".join(sorted(missing)),file=sys.stderr); return 2
    for lane in selected:
        print(f"=== verification lane: {lane['id']} ===",flush=True)
        for step in lane["steps"]:
            print("+ "+" ".join(step),flush=True)
            r=subprocess.run(step,cwd=root,check=False)
            if r.returncode:
                print(f"lane {lane['id']} FAILED with exit code {r.returncode}",file=sys.stderr); return r.returncode
        print(f"lane {lane['id']} PASS",flush=True)
    return 0
if __name__=="__main__": raise SystemExit(main())
