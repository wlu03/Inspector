#!/usr/bin/env python
"""Write (or --check) docs/tool-reference.md from the live MCP server.

    python scripts/gen_docs.py            # regenerate the reference
    python scripts/gen_docs.py --check    # exit 1 if the committed file is stale
"""

import pathlib
import sys

from inspector.docs_gen import build_tool_reference

_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "tool-reference.md"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    md = build_tool_reference()
    if "--check" in argv:
        current = _PATH.read_text() if _PATH.exists() else ""
        if current != md:
            print("docs/tool-reference.md is out of date - run: python scripts/gen_docs.py")
            return 1
        print("tool reference is in sync")
        return 0
    _PATH.write_text(md)
    print(f"wrote {_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
