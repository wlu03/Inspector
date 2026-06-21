"""Diagnose why local Electron didn't become CDP-ready: dev cmd, npm install,
the 9223 port, and electron's own stderr (which the adapter suppresses)."""

import json
import os
import shlex
import signal
import subprocess
import time
import urllib.request

from inspector.launch.detect import detect_project
from inspector.models import Surface

repo = os.path.abspath("examples/sample-buggy-electron")
proj = detect_project(repo, Surface.ELECTRON)
print("dev_command:", proj.dev_command)

nm = os.path.join(repo, "node_modules")
elec_bin = os.path.join(nm, ".bin", "electron")
print("node_modules present:", os.path.isdir(nm), "| electron bin:", os.path.exists(elec_bin))

if not os.path.isdir(nm):
    print("running npm install ...")
    r = subprocess.run(["npm", "install"], cwd=repo, capture_output=True, text=True, timeout=900)
    print("npm install exit:", r.returncode)
    if r.returncode != 0:
        print("npm stderr tail:\n", r.stderr[-1000:])

cmd = f"{proj.dev_command} -- --remote-debugging-port=9223 --no-sandbox"
print("launching:", cmd)
errf = open("/tmp/elec.err", "w")
p = subprocess.Popen(shlex.split(cmd), cwd=repo, start_new_session=True, stdout=errf, stderr=errf)

ws = None
try:
    for i in range(30):
        try:
            data = json.loads(urllib.request.urlopen("http://localhost:9223/json", timeout=2).read())
            page = next((t for t in data if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
            print(f"[{i}] /json target types={[t.get('type') for t in data]} page={bool(page)}")
            if page:
                ws = page["webSocketDebuggerUrl"]
                break
        except Exception as e:
            print(f"[{i}] 9223 not up ({type(e).__name__})")
        time.sleep(1.5)
    print("\nRESULT ws_url:", ws)
    if ws:
        from inspector.adapters.cdp_client import DOM_ELEMENTS_JS, CDPClient, parse_dom_elements
        try:
            cdp = CDPClient(ws)
            print("CDP connected")
            cdp.enable()
            print("CDP enabled")
            v = cdp.evaluate("JSON.stringify([window.innerWidth, window.innerHeight])")
            print("viewport eval:", v)
            raw = cdp.evaluate(DOM_ELEMENTS_JS)
            print("dom raw (300):", str(raw)[:300])
            els = parse_dom_elements(raw, 1280, 800)
            print("parsed elements:", len(els), [e.label for e in els[:10]])
            shot = cdp.screenshot()
            print("screenshot bytes:", len(shot))
            cdp.close()
        except Exception:
            import traceback
            traceback.print_exc()
finally:
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except Exception:
        p.terminate()
    errf.close()
    print("\n=== electron stdout/stderr (tail) ===")
    try:
        print(open("/tmp/elec.err").read()[-2000:])
    except Exception:
        print("(none)")
