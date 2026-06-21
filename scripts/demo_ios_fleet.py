#!/usr/bin/env python
"""Multi-simulator iOS fleet: boot N simulators in parallel (visible) and run the
a11y-state oracle on EACH — the iOS analog of the Android emulator fleet.

    INSPECTOR_IDB_BIN=~/.idb-venv/bin/idb python scripts/demo_ios_fleet.py [N]
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2
REPO = "examples/sample-buggy-ios"
IDB = os.environ.get("INSPECTOR_IDB_BIN", "idb")


def out(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k).stdout


def _find_app():
    return out("bash", "-c",
               f"find {REPO}/build -name SampleBuggyApp.app -path '*iphonesimulator*' | head -1").strip()


# 1) build once (reuse if already built from a prior run)
app = _find_app()
if not app:
    print(">> building the app once…", flush=True)
    subprocess.run(["bash", "-c",
                    f"cd {REPO} && xcodegen generate && xcodebuild -scheme SampleBuggyApp "
                    f"-sdk iphonesimulator -destination 'generic/platform=iOS Simulator' "
                    f"-derivedDataPath build CODE_SIGNING_ALLOWED=NO build"])
    app = _find_app()
print(">> app:", app)

# 2) claim N distinct simulators + boot them (visible)
devs = json.loads(out("xcrun", "simctl", "list", "devices", "available", "-j"))
udids = [u["udid"] for _rt, ds in devs["devices"].items() for u in ds if "iPhone" in u["name"]][:N]
print(f">> booting {len(udids)} simulators in parallel:", [u[:8] for u in udids], flush=True)
for u in udids:
    subprocess.run(["xcrun", "simctl", "boot", u])
subprocess.run(["open", "-a", "Simulator"])
for u in udids:
    subprocess.run(["xcrun", "simctl", "install", u, app])
print(">> installed on each — running the a11y oracle on every simulator", flush=True)


def run_oracle(u):
    env = {**os.environ, "INSPECTOR_IOS_UDID": u, "INSPECTOR_IDB_BIN": IDB}
    r = subprocess.run([sys.executable, "scripts/verify_ios_bugs.py"],
                       env=env, capture_output=True, text=True)
    lines = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
    return u, (lines[-1] if lines else (r.stderr or "no output")[-160:])


with ThreadPoolExecutor(max_workers=len(udids)) as ex:
    for u, summary in ex.map(run_oracle, udids):
        print(f"  sim {u[:8]} → {summary}")
