"""Reproduce the loop directly against LocalElectronAdapter to find what kills it
after the first action (CDP fragility / fallback crash)."""

import os
import time

from dotenv import load_dotenv

load_dotenv()

from inspector.adapters.base import InputAction  # noqa: E402
from inspector.adapters.local_electron import LocalElectronAdapter  # noqa: E402
from inspector.config import Config  # noqa: E402
from inspector.models import ActionType  # noqa: E402

repo = os.path.abspath("examples/sample-buggy-electron")
a = LocalElectronAdapter(Config())
a.launch(repo)
print("ready:", a.is_ready(timeout_s=60), "| viewport:", a.screen_size())

for i in range(5):
    try:
        shot = a.screenshot()
        els = a.detect_elements(shot)
        n = len(els) if els is not None else None
        print(f"[{i}] screenshot={len(shot)}B  detect_elements={n}")
        if els:
            e = els[min(4, len(els) - 1)]
            w, h = a.screen_size()
            cx, cy = e.center_px(w, h)
            if i == 0:
                a.input(InputAction(ActionType.TYPE, x=cx, y=cy, text="<script>alert('XSS')</script>"))
                print(f"     typed XSS into {e.label!r}")
            else:
                a.input(InputAction(ActionType.CLICK, x=cx, y=cy))
                print(f"     clicked {e.label!r} at ({cx},{cy})")
            print("     logs:", a.logs())
    except Exception:
        import traceback
        print(f"[{i}] EXCEPTION:")
        traceback.print_exc()
        break
    time.sleep(0.4)

a.teardown()
print("done")
