#!/usr/bin/env python
"""Run ONE headless autopilot agent on a repo + surface — the CLI form of test_app.

    python scripts/test_one.py <repo_path> [surface] [max_steps]

    python scripts/test_one.py examples/sample-buggy-electron electron
    INSPECTOR_ANDROID_PACKAGE=com.app python scripts/test_one.py . android
"""
import json
import sys

from inspector.autopilot import run_autopilot
from inspector.config import Config
from inspector.driver import get_driver
from inspector.models import Surface
from inspector.replay import write_replay_html, write_replay_video
from inspector.session import SessionManager

repo = sys.argv[1] if len(sys.argv) > 1 else "examples/sample-buggy-electron"
surface = Surface(sys.argv[2]) if len(sys.argv) > 2 else None
max_steps = int(sys.argv[3]) if len(sys.argv) > 3 else 8

cfg = Config.from_env()
mgr = SessionManager(cfg)
sess = mgr.create(repo, surface, goal="find UI bugs")
sid = sess.record.id
print(f">> {type(sess.adapter).__name__}: launching {repo} "
      f"({sess.record.surface.value}) ...", flush=True)
try:
    if not sess.launch():
        print(">> app did not become ready (check the dev command / toolchain)")
    else:
        rep = run_autopilot(sess, get_driver(cfg), "explore the app and find bugs", max_steps)
        print(">> RESULT:", json.dumps(
            {k: rep.get(k) for k in ("steps", "stop_reason", "findings_total", "verification")},
            indent=2, default=str))
        for f in rep.get("findings", []):
            print(f"   - [{f.get('severity')}] {f.get('summary', '')[:96]}")
        sess.trace.save_session(sess.record)
        write_replay_video(sess.trace.dir)
        print(">> replay:", write_replay_html(sess.trace.dir))
finally:
    mgr.stop(sid)
