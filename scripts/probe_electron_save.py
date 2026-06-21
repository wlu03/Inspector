"""Deterministic probe: does the Electron renderer-console pipe deliver a bug?

Launches the electron fixture, types a name into 'Your name', clicks the real Save,
and prints the logs + findings. If BUG-01's console.error / TypeError appears, the
CDP console capture on 9223 works end-to-end (isolates adapter vs brain).
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

import inspector.server as srv  # noqa: E402
from fastmcp import Client  # noqa: E402


def sc(r):
    return getattr(r, "structured_content", None) or getattr(r, "data", None) or {}


async def main() -> None:
    srv.CONFIG.trace_root = os.path.abspath("replays")
    repo = os.path.abspath("examples/sample-buggy-electron")
    async with Client(srv.mcp) as c:
        d = sc(await c.call_tool("launch_app", {"repo_path": repo, "surface": "electron"}))
        sid = d.get("session_id")
        print("launch:", d.get("ready"), d.get("state"), d.get("error", ""))
        if not d.get("ready"):
            return

        obs = sc(await c.call_tool("observe", {"session_id": sid, "include_image": False}))
        els = obs.get("elements", [])
        print("labels:", [e.get("label") for e in els if e.get("interactivity")][:20])

        def fid(els, pred):
            return next((e["id"] for e in els if e.get("interactivity") and pred((e.get("label") or "").strip().lower())), None)

        name_id = fid(els, lambda s: "your name" in s or s == "name" or "name" in s)
        print("name field id:", name_id)
        if name_id is not None:
            sc(await c.call_tool("act", {"session_id": sid, "type": "type",
                                         "target_id": name_id, "text": "Alice", "include_image": False}))

        obs2 = sc(await c.call_tool("observe", {"session_id": sid, "include_image": False}))
        save_id = fid(obs2.get("elements", []), lambda s: s == "save")
        print("save button id:", save_id)
        if save_id is not None:
            res = sc(await c.call_tool("act", {"session_id": sid, "type": "click",
                                               "target_id": save_id, "include_image": False}))
            print("LOGS AFTER SAVE:", res.get("logs"))

        fnd = await c.call_tool("get_findings", {"session_id": sid})
        findings = getattr(fnd, "data", None)
        print("FINDINGS:", findings)
        sc(await c.call_tool("stop", {"session_id": sid}))


if __name__ == "__main__":
    asyncio.run(main())
