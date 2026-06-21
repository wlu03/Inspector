#!/usr/bin/env python
"""Multi-agent Android fleet: boot N emulators in parallel and run one autopilot agent
per emulator against the same app — the "all emulators popping" demo.

    INSPECTOR_SHOW_EMULATOR=1 \
      python scripts/demo_android_fleet.py [repo] [apk] [package] [N] [steps]

Defaults to Super Productivity's prebuilt APK. Each agent gets its OWN emulator
(unique even port, -read-only ephemeral data) + installs the APK + drives a session.
"""
import dataclasses
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from inspector.autopilot import run_autopilot
from inspector.config import Config
from inspector.driver import get_driver
from inspector.models import Surface
from inspector.planes.android import LocalEmulatorRuntime, _sdk_bin
from inspector.session import SessionManager

repo = sys.argv[1] if len(sys.argv) > 1 else "demo-apps/super-productivity"
apk = sys.argv[2] if len(sys.argv) > 2 else \
    f"{repo}/android/app/build/outputs/apk/play/debug/app-play-debug.apk"
pkg = sys.argv[3] if len(sys.argv) > 3 else "com.superproductivity.superproductivity"
N = int(sys.argv[4]) if len(sys.argv) > 4 else 2
steps = int(sys.argv[5]) if len(sys.argv) > 5 else 5

cfg = Config.from_env()
adb = _sdk_bin("platform-tools", "adb")
rts = [LocalEmulatorRuntime(cfg) for _ in range(N)]
print(f">> booting {N} emulators in parallel:", [r.serial for r in rts], flush=True)
with ThreadPoolExecutor(max_workers=N) as ex:
    list(ex.map(lambda r: r.start(), rts))
print(">> all emulators online — installing + dispatching one agent each", flush=True)


def run_agent(rt):
    s = rt.serial
    subprocess.run([adb, "-s", s, "install", "-r", apk], capture_output=True, timeout=400)
    c = dataclasses.replace(cfg, android_serial=s, android_package=pkg)  # pin THIS emulator
    mgr = SessionManager(c)
    sess = mgr.create(repo, Surface.ANDROID, goal=f"find bugs on {s}")
    sid = sess.record.id
    try:
        if not sess.launch():
            return {"serial": s, "status": "not-ready"}
        rep = run_autopilot(sess, get_driver(c), "explore the app and find bugs", steps)
        return {"serial": s, "status": "ok", "steps": rep.get("steps"),
                "findings": rep.get("findings_total")}
    except Exception as exc:  # noqa: BLE001
        return {"serial": s, "status": "error", "detail": str(exc)[:160]}
    finally:
        mgr.stop(sid)


try:
    with ThreadPoolExecutor(max_workers=N) as ex:
        for r in ex.map(run_agent, rts):
            print("  ", r, flush=True)
finally:
    for rt in rts:
        try:
            rt.stop()
        except Exception:
            pass
    print(">> fleet torn down")
