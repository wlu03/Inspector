#!/usr/bin/env python
"""Serve the dashboard + replays over http so the Fix-with-Devin buttons work.

The per-finding 'Fix with Devin' button POSTs to /api/devin-fix — which only works
when the page is served (a file:// page can't POST). This wires the same action handler
the MCP uses and serves the trace root.

    python scripts/serve_dashboard.py     # prints a localhost URL; open replays from it
"""
import time

from inspector import server as mcp          # has _dashboard_action + _live_sessions
from inspector.config import Config
from inspector.dashboard import serve
from inspector.dashboard.build import build_dashboard

cfg = Config.from_env()
build_dashboard(cfg.trace_root)
serve.set_action_handler(mcp._dashboard_action)   # powers Fix with Devin (opens a PR)
serve.set_live_provider(mcp._live_sessions)        # powers the live feed
base = serve.ensure_server(cfg.trace_root)

print(f"\n  Dashboard:  {base}/dashboard.html")
print("  Open replays from there — each finding's 'Fix with Devin' opens a PR for THAT issue.")
print("  (Ctrl-C to stop)\n")
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass
