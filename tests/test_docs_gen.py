"""The generated MCP tool reference must list every tool and stay in sync with the file."""

import pathlib

from inspector import server as s
from inspector.docs_gen import build_tool_reference

_REF = pathlib.Path(__file__).resolve().parent.parent / "docs" / "tool-reference.md"


def test_reference_lists_every_tool():
    md = build_tool_reference()
    for name in s.CORE_TOOLS | s.ADVANCED_TOOLS:
        assert f"`{name}`" in md
    assert "read-only" in md and "destructive" in md


def test_reference_committed_file_is_in_sync():
    assert _REF.exists(), "run: python scripts/gen_docs.py"
    assert _REF.read_text() == build_tool_reference(), (
        "docs/tool-reference.md is stale - run: python scripts/gen_docs.py"
    )
