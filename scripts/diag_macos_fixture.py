"""Drive the macOS SwiftUI fixture through the adapter: build → launch → AX ground
→ tap Plus → read the count (BUG-01: +2)."""

import os
import time

from inspector.adapters.base import InputAction
from inspector.adapters.macos_native import MacNativeAdapter
from inspector.config import Config
from inspector.models import ActionType

a = MacNativeAdapter(Config())
repo = os.path.abspath("examples/sample-buggy-macos")
print("=== launch (xcodegen + xcodebuild macOS + open) ===", flush=True)
a.launch(repo)
print("app:", a.app, "| pid:", a.pid, "| app_path:", a._app_path, flush=True)
print("ready:", a.is_ready(timeout_s=30), "| window:", a.screen_size(), flush=True)


def count(els):
    c = [e for e in (els or []) if e.label.startswith("Count:")]
    return c[0].label if c else "?"


els = a.detect_elements(a.screenshot())
print("grounded labels:", [e.label for e in (els or []) if e.label], flush=True)
print("count before:", count(els), flush=True)

plus = next((e for e in (els or []) if e.label == "Plus"), None)
if plus:
    cx, cy = plus.center_px(*a.screen_size())
    a.input(InputAction(ActionType.CLICK, x=cx, y=cy))
    time.sleep(0.7)
    els = a.detect_elements(a.screenshot())
    print(f"count after ONE Plus at ({cx},{cy}):", count(els),
          "  <- BUG-01 if 'Count: 2' (correct would be 'Count: 1')", flush=True)

a.teardown()
print("done")
