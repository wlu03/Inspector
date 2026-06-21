"""End-to-end iOS adapter smoke test: launch (xcodegen+build+boot+install+launch),
is_ready, then a few observe/act cycles via simctl screenshot + idb a11y grounding."""

import os
import time

from dotenv import load_dotenv

load_dotenv()

from inspector.adapters.base import InputAction  # noqa: E402
from inspector.adapters.ios import IOSAdapter  # noqa: E402
from inspector.config import Config  # noqa: E402
from inspector.models import ActionType  # noqa: E402

repo = os.path.abspath("examples/sample-buggy-ios")
a = IOSAdapter(Config.from_env())
print("local mode:", a.plane.local)

print("=== launch (xcodegen + build + boot + install + launch) ===", flush=True)
try:
    a.launch(repo)
except Exception:
    import traceback
    print("LAUNCH EXCEPTION:")
    traceback.print_exc()

print("udid:", a.udid, "| bundle_id:", a.bundle_id, flush=True)
print("=== is_ready ===", flush=True)
print("ready:", a.is_ready(timeout_s=120), "| point_size:", a.screen_size(), flush=True)

for i in range(4):
    try:
        shot = a.screenshot()
        els = a.detect_elements(shot)
        n = len(els) if els is not None else None
        print(f"[{i}] screenshot={len(shot)}B  detect_elements={n}",
              [e.label for e in (els or [])[:8]], flush=True)
        if els:
            e = els[min(2, len(els) - 1)]
            cx, cy = e.center_px(*a.screen_size())
            a.input(InputAction(ActionType.CLICK, x=cx, y=cy))
            print(f"   tapped {e.label!r} at ({cx},{cy}); logs={a.logs()[:3]}", flush=True)
    except Exception:
        import traceback
        print(f"[{i}] EXCEPTION:")
        traceback.print_exc()
        break
    time.sleep(1.0)

a.teardown()
print("done")
