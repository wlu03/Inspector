"""Build the static dashboard: ensure each session has a replay, write dashboard.html.

The single entry point — pure-ish orchestration over `aggregate` + `render` + the
existing per-session `replay`. Idempotent: re-run any time to fold in new sessions.
"""

from __future__ import annotations

import json
import os

from .aggregate import (
    aggregate_stats,
    bug_ledger,
    latest_update,
    recurring_findings,
    scan_sessions,
)
from .render import render_index


def build_dashboard(trace_root: str | None = None, ensure_replays: bool = True) -> str:
    """Aggregate every session under `trace_root` into one `dashboard.html`.

    `ensure_replays` regenerates a per-session replay (html + video) for any
    session that has frames but no `index.html` yet, so every row is clickable.
    Returns the path to the written dashboard.html.
    """
    if trace_root is None:
        from ..config import Config
        trace_root = Config.from_env().trace_root
    os.makedirs(trace_root, exist_ok=True)

    summaries = scan_sessions(trace_root)

    if ensure_replays:
        for s in summaries:
            if s["has_replay"] or s["n_frames"] == 0:
                continue
            sdir = os.path.join(trace_root, s["id"])
            try:
                from ..replay import write_replay_html, write_replay_video
                write_replay_video(sdir)
                write_replay_html(sdir)
                s["has_replay"] = True
                s["replay_path"] = f"{s['id']}/index.html"
            except Exception:
                pass  # a single un-renderable session must not break the index

    stats = aggregate_stats(summaries)
    recurring = recurring_findings(trace_root)
    ledger = bug_ledger(trace_root)
    update = latest_update(trace_root)

    out = os.path.join(trace_root, "dashboard.html")
    with open(out, "w") as f:
        f.write(render_index(summaries, stats, recurring, ledger=ledger, update=update))

    # machine-readable companion for programmatic consumers (CI, the MCP tools).
    with open(os.path.join(trace_root, "dashboard.json"), "w") as f:
        json.dump({"stats": stats, "sessions": summaries, "recurring": recurring,
                   "ledger": ledger, "update": update}, f, indent=2)

    return out
