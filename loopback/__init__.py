"""LoopBack — a computer-use testing MCP for coding agents.

The package is intentionally importable without the heavy optional SDKs
(fastmcp, e2b-desktop, replicate). Those are lazy-imported only where used,
so `import loopback` and the pure unit tests work with just pydantic + pillow.
"""

__version__ = "0.0.1"
