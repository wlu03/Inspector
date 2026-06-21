#!/usr/bin/env python
"""Multi-agent iOS fleet via the AUTOPILOT: N agents drive N simulators in parallel,
each screenshotting every action, all collected into ONE dashboard (the parallel report).

    INSPECTOR_IDB_BIN=~/.idb-venv/bin/idb python scripts/demo_ios_agents.py [N] [steps]
"""
import dataclasses
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from inspector.autopilot import run_autopilot
from inspector.config import Config
from inspector.driver import get_driver
from inspector.models import Surface
from inspector.parallel_report import write_parallel_report
from inspector.replay import write_replay_html, write_replay_video
from inspector.session import SessionManager

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 6
REPO = "examples/sample-buggy-ios"
GOALS = [
    "Explore the wishlist home: add a new item and watch the count.",
    "Open Wish Details, fill the item name + price, tap Continue, then go back.",
    "Change the appearance theme and confirm the 'Current theme' caption.",
    "Open About and try Clear wishlist; check it returns to the wishlist.",
]
cfg = Config.from_env()

# 1) build the app ONCE, then make every agent skip the rebuild
print(">> building the Wishlist app once…", flush=True)
subprocess.run(["bash", "-c",
                f"cd {REPO} && xcodegen generate >/dev/null 2>&1 && xcodebuild -scheme "
                f"SampleBuggyApp -sdk iphonesimulator -destination 'generic/platform=iOS "
                f"Simulator' -derivedDataPath build CODE_SIGNING_ALLOWED=NO build >/dev/null 2>&1"])
os.environ["INSPECTOR_IOS_PREBUILT"] = "1"

# 2) boot N distinct simulators (visible)
devs = json.loads(subprocess.run(["xcrun", "simctl", "list", "devices", "available", "-j"],
                                 capture_output=True, text=True).stdout)
udids = [u["udid"] for _rt, ds in devs["devices"].items() for u in ds if "iPhone" in u["name"]][:N]
for u in udids:
    subprocess.run(["xcrun", "simctl", "boot", u], capture_output=True)
subprocess.run(["open", "-a", "Simulator"])
print(f">> {len(udids)} simulators booted — dispatching {len(udids)} autopilot agents", flush=True)


def run_agent(idx_udid):
    idx, udid = idx_udid
    goal = GOALS[idx % len(GOALS)]
    c = dataclasses.replace(cfg, macos_ios_udid=udid)   # pin THIS simulator
    mgr = SessionManager(c)
    sess = mgr.create(REPO, Surface.IOS, goal=goal)
    sid = sess.record.id
    sess.record.alias = f"sim-{udid[:6]}"
    rec = {"part": sess.record.alias, "session_id": sid, "goal": goal}
    try:
        if not sess.launch():
            return {**rec, "status": "not-ready", "steps": 0, "findings_total": 0, "findings": []}
        rep = run_autopilot(sess, get_driver(c), goal, STEPS)
        return {**rec, "status": "ok", "steps": rep.get("steps"),
                "findings_total": rep.get("findings_total"), "findings": rep.get("findings", [])}
    except Exception as exc:  # noqa: BLE001
        return {**rec, "status": "error", "detail": str(exc)[:140], "steps": 0,
                "findings_total": 0, "findings": []}
    finally:
        try:
            sess.trace.save_session(sess.record)
            write_replay_video(sess.trace.dir)
            write_replay_html(sess.trace.dir)
        except Exception:
            pass
        mgr.stop(sid)


with ThreadPoolExecutor(max_workers=len(udids)) as ex:
    results = list(ex.map(run_agent, list(enumerate(udids))))

# 3) collect every agent's screenshots + findings into ONE collective dashboard
merged, seen = [], set()
for r in results:
    for f in r.get("findings", []):
        k = (f.get("summary") or "").lower()[:120]
        if k and k not in seen:
            seen.add(k)
            merged.append(f)
parts = [{k: r[k] for k in r if k != "findings"} for r in results]
plan = [{"name": r["part"], "goal": r["goal"]} for r in results]
report = write_parallel_report(cfg.trace_root, plan, parts, merged)

print("\n>> agents:")
for r in parts:
    print(f"   [{r['part']}] {r['status']}  steps={r.get('steps')}  findings={r.get('findings_total')}")
print(f">> {len(merged)} unique findings")
print(">> collective dashboard:", report)
subprocess.run(["open", report])
