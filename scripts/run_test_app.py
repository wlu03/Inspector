"""Live end-to-end test of the autonomous `test_app` tool: one call launches the
app in a sandbox, the embedded driver explores it (VLM-guided, heuristic fallback),
and findings come back. Time-bounded, not step-capped.

Usage:  python scripts/run_test_app.py [repo_path] [minutes]
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

import inspector.server as srv  # noqa: E402
from fastmcp import Client  # noqa: E402

REPO = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "examples/sample-buggy-app")
MINUTES = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0


def sc(result):
    return getattr(result, "structured_content", None) or getattr(result, "data", None)


async def main() -> None:
    srv.CONFIG.trace_root = os.path.abspath("replays")
    srv.CONFIG.max_wall_clock_s = int(MINUTES * 60)  # time budget, not a step cap
    srv.CONFIG.max_iterations = 1000                 # effectively time-bounded

    async with Client(srv.mcp) as client:
        print(f"test_app({REPO})  budget={MINUTES} min, no step cap ...", flush=True)
        # no max_steps -> runs until the driver is done or the wall-clock/iteration guard
        r = await client.call_tool(
            "test_app",
            {"repo_path": REPO, "goal": "exercise every flow and find bugs"},
        )
        d = sc(r) or {}
        print(f"\nready={d.get('ready')}  steps={d.get('steps')}  stop={d.get('stop_reason')}")
        if d.get("error"):
            print("error:", d["error"])
        print(f"findings_total={d.get('findings_total')}")
        for f in (d.get("findings") or []):
            print(f"  - [{f.get('severity')}] {str(f.get('summary'))[:80]}  @ {f.get('suspected_area')}")
        print("\nexplore history:")
        for h in (d.get("history") or []):
            print(f"   #{h.get('step')} {h.get('action')} {h.get('target_label','')!r} "
                  f"changed={h.get('changed')} | {h.get('reason','')}")
        print("\nreplay:", d.get("replay"))


if __name__ == "__main__":
    asyncio.run(main())
