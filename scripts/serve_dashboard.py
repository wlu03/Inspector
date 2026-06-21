#!/usr/bin/env python
"""Serve the dashboard + replays over http so the Fix-with-Devin buttons work.

The per-finding 'Fix with Devin' button POSTs to /api/devin-fix — which only works
when the page is served (a file:// page can't POST). This wires the same action handler
the MCP uses and serves the trace root.

    python scripts/serve_dashboard.py     # prints a localhost URL; open replays from it
"""
import os
import sys

# Auto-bootstrap: if `inspector` isn't importable (ran with the system python instead of
# the project venv), re-exec this script with the venv's python so it just works.
try:
    import inspector  # noqa: F401
except ModuleNotFoundError:
    _venv_py = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python")
    if os.path.exists(_venv_py) and os.path.realpath(sys.executable) != os.path.realpath(_venv_py):
        os.execv(_venv_py, [_venv_py, *sys.argv])
    raise

import time

from inspector import server as mcp          # has _dashboard_action + _live_sessions
from inspector.config import Config
from inspector.dashboard import serve
from inspector.dashboard.build import build_dashboard

cfg = Config.from_env()
build_dashboard(cfg.trace_root, ensure_replays=False)   # replays already exist → serve fast
serve.set_action_handler(mcp._dashboard_action)   # powers Fix with Devin (opens a PR)
serve.set_live_provider(mcp._live_sessions)        # powers the live feed
base = serve.ensure_server(cfg.trace_root)

print(f"\n  Dashboard:  {base}/dashboard.html", flush=True)
print("  Open replays from there — each finding's 'Fix with Devin' opens a PR for THAT issue.",
      flush=True)
print("  (Ctrl-C to stop)\n", flush=True)
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass
