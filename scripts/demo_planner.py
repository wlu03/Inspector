#!/usr/bin/env python
"""Demo the planner + parallel fan-out on any frontend repo.

    python scripts/demo_planner.py <repo_path> [surface] [max_agents] [max_steps]

    # examples
    python scripts/demo_planner.py examples/sample-buggy-electron electron
    python scripts/demo_planner.py examples/sample-buggy-app web 4 5
    python scripts/demo_planner.py ~/code/your-electron-app electron

The planner looks at the app's first screen, decomposes it into parts, and dispatches
one headless agent per part in parallel — then prints the plan + merged findings.
Needs the keys in .env; for Electron/web, `node` must be on PATH.
"""
import sys
import time

from inspector.config import Config
from inspector.models import Surface
from inspector.parallel import planned_verify

repo = sys.argv[1] if len(sys.argv) > 1 else "examples/sample-buggy-electron"
surface = Surface(sys.argv[2]) if len(sys.argv) > 2 else Surface.ELECTRON
max_agents = int(sys.argv[3]) if len(sys.argv) > 3 else 4
max_steps = int(sys.argv[4]) if len(sys.argv) > 4 else 5

print(f">> planning + fanning out on {repo} ({surface.value}), "
      f"<= {max_agents} agents x {max_steps} steps ...", flush=True)
t0 = time.time()
res = planned_verify(Config.from_env(), repo, surface, "find UI bugs", max_steps, max_agents)

print(f"\n=== PLAN ({len(res['plan'])} parts) ===")
for p in res["plan"]:
    print(f"  • {p['name']}: {p['goal'][:90]}")
print(f"\n=== AGENTS ({res['agents']}) — finished in {time.time()-t0:.0f}s ===")
for p in res["parts"]:
    print(f"  [{p['part']:<16}] {p['status']}  steps={p.get('steps')}  findings={p.get('findings_total')}")
print(f"\n=== MERGED FINDINGS ({res['total_unique_findings']} unique) ===")
for f in res["merged_findings"]:
    print(f"  - [{f.get('severity')}] {f.get('summary','')[:96]}")
if res.get("parallel_report"):
    print("\nParallel report:", res["parallel_report"])
    import subprocess
    subprocess.run(["open", res["parallel_report"]])   # one page: all agents + screenshots
