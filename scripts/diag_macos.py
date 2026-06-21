"""End-to-end macOS-native adapter smoke test: drive Calculator (7 + 3 = 10)
through the adapter — launch, AX grounding, center_px taps, read the result."""

import time

from inspector.adapters.base import InputAction
from inspector.adapters.macos_native import MacNativeAdapter
from inspector.config import Config
from inspector.models import ActionType

a = MacNativeAdapter(Config(macos_app="Calculator"))
print("=== launch Calculator ===", flush=True)
a.launch(repo_path=".", dev_command="open -a Calculator")
print("pid:", a.pid, "| ready:", a.is_ready(timeout_s=30), "| window points:", a.screen_size(), flush=True)


def find(els, label):
    return next((e for e in els if e.label == label), None)


def display(els):
    st = [e for e in (els or []) if e.role == "statictext" and e.label]
    return st[-1].label.replace("‎", "") if st else "?"


def tap(a, el):
    w, h = a.screen_size()
    cx, cy = el.center_px(w, h)
    a.input(InputAction(ActionType.CLICK, x=cx, y=cy))
    time.sleep(0.35)
    return cx, cy


els = a.detect_elements(a.screenshot())
print(f"elements: {len(els) if els else els}", flush=True)
print("buttons:", [e.label for e in (els or []) if e.interactivity][:16], flush=True)
print("display before:", display(els), flush=True)

for lbl in ("Clear", "7", "Add", "3", "Equals"):
    el = find(els, lbl)
    if not el:
        print(f"  !! '{lbl}' not found", flush=True)
        continue
    cx, cy = tap(a, el)
    print(f"  tapped {lbl!r} at window-pt ({cx},{cy})", flush=True)
    els = a.detect_elements(a.screenshot())

print("display after 7+3=:", display(els), "(expect 10)", flush=True)
print("screenshot bytes:", len(a.screenshot()), flush=True)
a.teardown()
print("done")
