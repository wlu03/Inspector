"""Import-safe entry point for tooling that loads the server by file path,
e.g. ``fastmcp inspect mcp_server.py:mcp``.

Running ``inspector/server.py`` directly breaks on its relative imports; importing
the package here avoids that. Re-exports the FastMCP application object.
"""

from inspector.server import mcp

__all__ = ["mcp"]
