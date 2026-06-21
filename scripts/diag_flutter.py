"""End-to-end Flutter→iOS smoke test: build the Flutter app, boot the sim, launch,
and ground it. Flutter renders to a canvas, so detect_elements should fall through
from the (sparse) a11y tree to OmniParser vision grounding."""

import os
import time

from dotenv import load_dotenv

load_dotenv()

from inspector.adapters.base import InputAction  # noqa: E402
from inspector.adapters.ios import IOSAdapter  # noqa: E402
from inspector.config import Config  # noqa: E402
from inspector.models import ActionType  # noqa: E402

repo = os.path.abspath("examples/sample-buggy-flutter")
a = IOSAdapter(Config.from_env())
print("flutter_bin:", a._flutter_bin, "| idb:", a._idb, flush=True)

print("=== launch (flutter build ios + boot + install + launch) ===", flush=True)
try:
    a.launch(repo)
except Exception:
    import traceback
    print("LAUNCH EXCEPTION:")
    traceback.print_exc()

print("udid:", a.udid, "| bundle_id:", a.bundle_id, "| process:", a._app_process, flush=True)
print("ready:", a.is_ready(timeout_s=120), "| point_size:", a.screen_size(), flush=True)

def count(els):
    c = [e for e in (els or []) if e.label in "0123456789" and len(e.label) == 1]
    return c[0].label if c else "?"


def find(els, label):
    return next((e for e in (els or []) if e.label == label), None)


els = a.detect_elements(a.screenshot())
srcs = sorted({e.source for e in (els or [])})
print("grounding source:", srcs, "| labels:", [e.label for e in (els or []) if e.label], flush=True)
print("count before:", count(els), flush=True)

# BUG-01: tapping Plus once should make the count 1, but it increments by 2 -> 2.
plus = find(els, "Plus")
if plus:
    cx, cy = plus.center_px(*a.screen_size())
    a.input(InputAction(ActionType.CLICK, x=cx, y=cy))
    time.sleep(1.2)
    els = a.detect_elements(a.screenshot())
    print(f"count after ONE Plus tap at ({cx},{cy}):", count(els),
          "  <- BUG-01 if '2' (correct would be '1')", flush=True)

a.teardown()
print("done")
