"""CLI: build the static dashboard over the trace tree and (optionally) open it.

    python -m inspector.dashboard                 # build at ~/.inspector/sessions
    python -m inspector.dashboard --open          # build + open in the browser
    python -m inspector.dashboard --trace-root X  # build over a specific tree
"""

from __future__ import annotations

import argparse
import webbrowser

from ..config import Config
from .build import build_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(prog="inspector.dashboard")
    parser.add_argument("--trace-root", default=None, help="trace tree (default: config)")
    parser.add_argument("--open", action="store_true", help="open the dashboard after building")
    parser.add_argument("--no-replays", action="store_true",
                        help="skip regenerating missing per-session replays")
    args = parser.parse_args()

    trace_root = args.trace_root or Config.from_env().trace_root
    path = build_dashboard(trace_root, ensure_replays=not args.no_replays)
    print(f"dashboard → {path}")
    if args.open:
        webbrowser.open(f"file://{path}")


if __name__ == "__main__":
    main()
