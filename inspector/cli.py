"""``inspector-mcp`` command-line entry point.

Two subcommands:
  inspector-mcp serve [--http] [--host H] [--port P] [--path /mcp]   run the MCP server
  inspector-mcp doctor                                               check env / keys / deps

``serve`` is the default when no subcommand is given, so ``inspector-mcp`` and
``inspector-mcp --http`` both start the server (back-compatible with `python -m
inspector.server`).
"""

from __future__ import annotations

import sys

_HELP = (
    "inspector-mcp — MCP server for agent-driven app testing\n\n"
    "Usage:\n"
    "  inspector-mcp serve [--http] [--host H] [--port P] [--path /mcp]\n"
    "  inspector-mcp doctor\n\n"
    "serve is the default when no subcommand is given.\n"
)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "serve"

    if cmd in ("-h", "--help", "help"):
        print(_HELP)
        return
    if cmd == "doctor":
        from .doctor import main as doctor_main

        raise SystemExit(doctor_main())
    if cmd == "serve":
        argv = argv[1:]
    # Default / unknown leading flag → serve (so `inspector-mcp --http` works).
    from .server import main as serve_main

    serve_main(argv)


if __name__ == "__main__":
    main()
