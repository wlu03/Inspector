"""Drive the M0 loop through the real MCP client (FastMCP in-memory transport) —
exactly the path Claude Code / Cursor use. Proves the loop works behind the server.

Exercises (a) console capture, (b) cropped screenshots, (c) the MCP tool surface.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

import inspector.server as srv  # noqa: E402
from fastmcp import Client  # noqa: E402

REPO = os.path.abspath("examples/sample-buggy-app")


def sc(result):
    """Extract structured content from a FastMCP tool result, across versions."""
    return getattr(result, "structured_content", None) or getattr(result, "data", None)


async def main() -> None:
    srv.CONFIG.trace_root = os.path.abspath("replays")  # keep replays in the project

    async with Client(srv.mcp) as client:
        tools = [t.name for t in await client.list_tools()]
        print("MCP tools:", tools)

        print("\n[launch_app]")
        r = await client.call_tool(
            "launch_app", {"repo_path": REPO, "surface": "web", "goal": "verify the save flow"}
        )
        launched = sc(r)
        print(" ", launched)
        sid = launched["session_id"]

        print("\n[observe]")
        r = await client.call_tool("observe", {"session_id": sid})
        elements = sc(r)["elements"]
        print(f"  {len(elements)} elements")
        save = next((e for e in elements if "save" in (e.get("label") or "").lower()), None)
        for e in elements:
            print(f"   #{e['id']} [{e['role']}] {e['label']!r:26.26} click={e['interactivity']}")

        if save:
            print(f"\n[act] click Save -> #{save['id']}")
            r = await client.call_tool(
                "act", {"session_id": sid, "type": "click", "target_id": save["id"]}
            )
            acted = sc(r)
            print("  changed:", acted.get("changed"))
            print("  logs   :", acted.get("logs"))

            await asyncio.sleep(1.2)  # let the CDP console line flush

            print("\n[verify]")
            r = await client.call_tool(
                "verify", {"session_id": sid, "expectation": "a 'Saved' confirmation appears"}
            )
            print(" ", sc(r))

        print("\n[get_findings]")
        r = await client.call_tool("get_findings", {"session_id": sid})
        print(" ", sc(r))

        print("\n[stop]")
        r = await client.call_tool("stop", {"session_id": sid})
        print(" ", sc(r))


if __name__ == "__main__":
    asyncio.run(main())
