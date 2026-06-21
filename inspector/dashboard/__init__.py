"""Inspector dashboard — a static aggregator over every session's trace.

Pure, zero-dependency layer that reads `~/.inspector/sessions/` (the on-disk
trace from docs/06), aggregates every run into one replayable index, and exposes
the fix-loop context the host coding agent acts on (live agent integration via
the MCP `fix_finding` / `update_finding_status` tools).

  aggregate.py  scan/load/stat the trace tree + fix-prompt synthesis (pure)
  render.py     render the self-contained dashboard.html (pure)
  build.py      orchestrate: ensure per-session replays, write dashboard.html
"""

from .build import build_dashboard
from .serve import ensure_server, publish
from .aggregate import (
    aggregate_stats,
    collect_all_findings,
    fix_prompt,
    load_session_detail,
    recurring_findings,
    scan_sessions,
)

__all__ = [
    "build_dashboard",
    "ensure_server",
    "publish",
    "scan_sessions",
    "load_session_detail",
    "aggregate_stats",
    "collect_all_findings",
    "recurring_findings",
    "fix_prompt",
]
