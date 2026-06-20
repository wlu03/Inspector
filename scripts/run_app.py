"""Smoke-test launch + detection on ANY web app repo (for task #7).

Usage:  python scripts/run_app.py /path/to/some/web/app

Validates the hard parts on a real app — framework/dev-command detection,
readiness, and OmniParser detection quality — and writes a replay you can open
to see what the agent would see. It does NOT drive a full fix loop (that's #6,
via a real Claude Code agent).
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

import inspector.server as srv  # noqa: E402
from fastmcp import Client  # noqa: E402


def sc(result):
    return getattr(result, "structured_content", None) or getattr(result, "data", None)


async def main(repo: str) -> None:
    repo = os.path.abspath(repo)
    srv.CONFIG.trace_root = os.path.abspath("replays")
    async with Client(srv.mcp) as client:
        print(f"launching {repo} ...", flush=True)
        launched = sc(await client.call_tool("launch_app", {"repo_path": repo, "surface": "web"}))
        print("launch:", launched, flush=True)
        sid = launched["session_id"]

        if launched.get("ready"):
            obs = sc(await client.call_tool("observe", {"session_id": sid}))
            els = obs["elements"]
            print(f"\n{len(els)} elements detected:")
            for e in els[:40]:
                print(f"  #{e['id']} [{e['role']}] {e['label']!r:30.30} click={e['interactivity']}")
        else:
            print("NOT READY — check framework detection / dev command / port.")

        stopped = sc(await client.call_tool("stop", {"session_id": sid}))
        print("\nreplay:", stopped.get("replay"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/run_app.py /path/to/web/app")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
