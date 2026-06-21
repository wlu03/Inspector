#!/usr/bin/env python3
"""Demo the Android adapter end-to-end against the sample-buggy-android app.

Usage:
  E2B_API_KEY=... python scripts/demo_android.py

Walks through the full Inspector loop on the Android surface:
  1. Boot E2B sandbox + Redroid container
  2. Build the Expo app -> APK
  3. Install + launch in the Android emulator
  4. Screenshot -> observe
  5. Tap the "Save" button
  6. Detect the crash (TypeError)
  7. Tear down
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inspector.config import Config
from inspector.adapters.android import AndroidAdapter
from inspector.adapters.base import InputAction
from inspector.models import ActionType


def main():
    print("=== Inspector Android Demo ===\n")

    config = Config.from_env()
    if not config.e2b_api_key:
        print("ERROR: E2B_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)

    adapter = AndroidAdapter(config)

    repo_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples", "sample-buggy-android",
    )
    print(f"Sample app: {repo_path}\n")

    # --- Step 1: Launch ---
    print("[1/6] Launching (E2B sandbox + Redroid + build + install) ...")
    print("       This takes several minutes on first run (npm install, Gradle build).")
    try:
        adapter.launch(repo_path)
    except Exception as e:
        print(f"  ERROR during launch: {e}")
        adapter.teardown()
        sys.exit(1)

    # --- Step 2: Wait for ready ---
    print("[2/6] Waiting for app to be ready ...")
    ready = adapter.is_ready(timeout_s=30)
    if not ready:
        print("  App did not become ready within 30s.")
        adapter.teardown()
        sys.exit(1)
    print("  App is ready.\n")

    # --- Step 3: Screenshot ---
    print("[3/6] Taking screenshot ...")
    png = adapter.screenshot()
    screenshot_path = "/tmp/inspector_android_demo.png"
    with open(screenshot_path, "wb") as f:
        f.write(png)
    print(f"  Screenshot saved: {screenshot_path} ({len(png)} bytes)")
    w, h = adapter.screen_size()
    print(f"  Screen size: {w}x{h}\n")

    # --- Step 4: Check logs before action ---
    print("[4/6] Logs before action ...")
    logs = adapter.logs()
    if logs:
        for line in logs[:5]:
            print(f"  {line}")
    else:
        print("  (no logs yet)")
    print()

    # --- Step 5: Tap the Save button ---
    tap_x = w // 2
    tap_y = int(h * 0.55)
    print(f"[5/6] Tapping 'Save' button at ({tap_x}, {tap_y}) ...")
    adapter.input(InputAction(type=ActionType.CLICK, x=tap_x, y=tap_y))
    time.sleep(2)

    # Screenshot after tap
    png_after = adapter.screenshot()
    after_path = "/tmp/inspector_android_demo_after.png"
    with open(after_path, "wb") as f:
        f.write(png_after)
    print(f"  Post-tap screenshot: {after_path}")

    # Check for crash
    print()
    print("[6/6] Checking for crash ...")
    logs_after = adapter.logs()
    crash_found = False
    for line in logs_after:
        if any(kw in line.lower() for kw in ["crash", "fatal", "typeerror", "not running"]):
            crash_found = True
        print(f"  {line}")

    print()
    if crash_found:
        print("CRASH DETECTED — the Save button triggers a TypeError.")
        print("This is the bug Inspector catches and reports back to the agent.")
    else:
        print("No crash detected in logs.")

    # --- Teardown ---
    print("\nTearing down ...")
    adapter.teardown()
    print("Done.\n")

    print("=== Demo complete ===")
    print(f"Screenshots: {screenshot_path}, {after_path}")


if __name__ == "__main__":
    main()
