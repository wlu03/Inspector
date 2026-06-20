"""Diagnose the Chromium step: after vite is up, launch chrome and watch for the
process + window, capture chrome logs, screenshot after a longer wait.
"""

from __future__ import annotations

import os
import time

from dotenv import load_dotenv

load_dotenv()

from loopback.adapters.web import WebAdapter  # noqa: E402
from loopback.config import Config  # noqa: E402

REPO = os.path.abspath("examples/sample-buggy-app")
cfg = Config.from_env()
a = WebAdapter(cfg)


def sh(cmd: str) -> str:
    r = a.sandbox.run_sync(cmd)
    return (getattr(r, "stdout", "") or "").strip() if r else ""


try:
    print("launching (node + npm + vite) ...", flush=True)
    a.launch(REPO)
    url = f"http://localhost:{a._port}/"
    print("vite ready:", a._wait_http(url, 120), flush=True)

    print("chrome version:", sh("google-chrome --version 2>&1 || true"), flush=True)
    print("curl page head:", sh(f"curl -fsS {url} | head -c 120 || true"), flush=True)

    a.sandbox.run_bg(
        f"google-chrome --app={url} --no-sandbox --disable-gpu "
        "--window-position=0,0 --window-size=1280,800 --no-first-run "
        "--disable-session-crashed-bubble --user-data-dir=/tmp/lb 2>&1"
    )

    for i in range(7):
        time.sleep(4)
        procs = sh("pgrep -a chrome | head -3 || true")
        wins = sh("xdotool search --onlyvisible --name '.+' 2>/dev/null | wc -l || true")
        names = sh("for w in $(xdotool search --onlyvisible --name '.+' 2>/dev/null); do xdotool getwindowname $w; done || true")
        print(f"t={i*4+4:2d}s  chrome_running={'yes' if procs else 'NO'}  visible_windows={wins}", flush=True)
        if names:
            print("        window names:", names.replace("\n", " | "), flush=True)

    print("\nrecent dev/chrome logs:", flush=True)
    for line in a.sandbox.drain_logs()[-25:]:
        print("  |", line.rstrip(), flush=True)

    # try to activate the newest window then screenshot
    wid = sh("xdotool search --onlyvisible --name '.+' | tail -1")
    if wid:
        a.sandbox.run_sync(f"xdotool windowactivate {wid}")
        a.sandbox.run_sync(f"xdotool windowsize {wid} 1280 800")
        a.sandbox.run_sync(f"xdotool windowmove {wid} 0 0")
        time.sleep(2)
    png = a.sandbox.screenshot()
    out = os.path.abspath("scripts/_chrome_debug.png")
    with open(out, "wb") as f:
        f.write(png)
    print(f"\nscreenshot: {len(png)} bytes -> {out}", flush=True)
finally:
    a.teardown()
    print("done.", flush=True)
