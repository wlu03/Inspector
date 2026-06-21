"""Live Cartographer Phase 0 run: launch an electron app + region-decomposed,
deterministic lens sweep + print the ranked fix list."""

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from inspector.cartographer import run_regions  # noqa: E402
from inspector.config import Config  # noqa: E402
from inspector.models import Surface  # noqa: E402
from inspector.session import SessionManager  # noqa: E402

repo = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "examples/sample-buggy-counter")
surface = Surface(sys.argv[2]) if len(sys.argv) > 2 else Surface.ELECTRON
mgr = SessionManager(Config.from_env())
session = mgr.create(repo, surface, "cartographer phase 0")
print("launching", repo, flush=True)
ready = session.launch()
print("ready:", ready, flush=True)
try:
    if ready:
        report = run_regions(session)
        print("=== regions ===")
        for r in report["regions"]:
            print(f"  {r['region_id']} {r['title']!r} [{r['role_class']}] members={r['members']}")
        print(f"\nhypotheses_tested={report['hypotheses_tested']}  confirmed={report['confirmed']}\n")
        print("=== fixes ===")
        for f in report["fixes"]:
            print(f"  [{f['severity']}] ({f['lens']}) {f['issue']}")
            print(f"     oracle: {f['evidence'].get('oracle')}")
            print(f"     fix:    {f['suggested_fix']}")
finally:
    mgr.stop(session.record.id)
    print("\ndone")
