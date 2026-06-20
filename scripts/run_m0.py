"""Live M0 driver: launch the sample-buggy-app in an E2B sandbox, wait until
ready, screenshot it, then try the detector. Proves the full WebAdapter pipeline
(Node install -> npm install -> vite -> readiness -> chrome -> screenshot).

The detector step needs Replicate credit; it's wrapped so the rest still proves out.
"""

from __future__ import annotations

import os
import time

from dotenv import load_dotenv

load_dotenv()

from inspector.adapters.web import WebAdapter  # noqa: E402
from inspector.config import Config  # noqa: E402
from inspector.perception.detector import OmniParserDetector  # noqa: E402

REPO = os.path.abspath("examples/sample-buggy-app")
SHOT = os.path.abspath("scripts/_m0_screenshot.png")


def main() -> None:
    cfg = Config.from_env()
    adapter = WebAdapter(cfg)
    t0 = time.time()
    try:
        print(f"[{time.time() - t0:5.1f}s] launching {REPO} ...", flush=True)
        adapter.launch(REPO)
        print(f"[{time.time() - t0:5.1f}s] waiting for readiness ...", flush=True)
        ready = adapter.is_ready()
        print(f"[{time.time() - t0:5.1f}s] ready = {ready}", flush=True)
        if not ready:
            print("dev server never became ready; recent logs:")
            for line in adapter.logs()[-20:]:
                print("  |", line.rstrip())
            return

        png = adapter.screenshot()
        with open(SHOT, "wb") as f:
            f.write(png)
        print(f"[{time.time() - t0:5.1f}s] screenshot: {len(png)} bytes -> {SHOT}", flush=True)

        print(f"[{time.time() - t0:5.1f}s] running detector (OmniParser) ...", flush=True)
        try:
            elements = OmniParserDetector(cfg).detect(png)
            print(f"detected {len(elements)} elements:")
            for e in elements[:12]:
                print(f"  #{e.id} [{e.role}] {e.label!r:40.40} bbox={e.bbox} click={e.interactivity}")
        except Exception as exc:  # noqa: BLE001
            print(f"DETECTOR STEP BLOCKED: {type(exc).__name__}: {str(exc)[:240]}")
            print("(the launch -> ready -> screenshot pipeline above is the proof)")
    finally:
        print(f"[{time.time() - t0:5.1f}s] tearing down ...", flush=True)
        adapter.teardown()
        print("done.", flush=True)


if __name__ == "__main__":
    main()
