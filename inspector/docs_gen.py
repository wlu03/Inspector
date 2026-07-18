"""Generate the MCP tool reference from the live server, so the docs cannot drift.

`build_tool_reference()` introspects `inspector.server.mcp` and returns markdown.
`scripts/gen_docs.py` writes it to `docs/tool-reference.md`, and a test asserts the
committed file matches, so changing the tool surface without regenerating fails CI.
"""

from __future__ import annotations

import asyncio


def _kind(tool) -> str:
    """One-word annotation kind for a tool (matches the annotation presets)."""
    a = getattr(tool, "annotations", None)
    if a is None:
        return "unknown"
    if getattr(a, "readOnlyHint", False):
        return "read-only"
    if getattr(a, "destructiveHint", False):
        return "destructive"
    if getattr(a, "openWorldHint", False):
        return "external"
    return "write"


def _first_line(text: str | None) -> str:
    return (text or "").strip().split("\n", 1)[0].strip()


async def _collect() -> str:
    from . import server as s

    total = len(s.CORE_TOOLS) + len(s.ADVANCED_TOOLS)
    out: list[str] = [
        "# MCP tool reference",
        "",
        "_Generated from the server by `scripts/gen_docs.py`. Do not edit by hand;",
        "run `python scripts/gen_docs.py` to regenerate._",
        "",
        f"The default `core` profile exposes {len(s.CORE_TOOLS)} tools; "
        f"`INSPECTOR_PROFILE=full` exposes all {total}.",
        "",
    ]
    for title, names in [
        ("Core tools (default profile)", sorted(s.CORE_TOOLS)),
        ("Advanced tools (`INSPECTOR_PROFILE=full`)", sorted(s.ADVANCED_TOOLS)),
    ]:
        out += [f"## {title}", "", "| Tool | Kind | Description |", "|---|---|---|"]
        for name in names:
            try:
                tool = await s.mcp.get_tool(name)
            except Exception:
                continue
            out.append(f"| `{name}` | {_kind(tool)} | {_first_line(tool.description)} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_tool_reference() -> str:
    """Render the MCP tool reference markdown (sync wrapper around the async server)."""
    return asyncio.run(_collect())
