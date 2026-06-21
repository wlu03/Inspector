#!/usr/bin/env python3
"""Demo the iOS adapter end-to-end against the sample-buggy-ios app.

Usage:
  # With a running tart VM:
  LOOPBACK_MACOS_HOST=<vm-ip> python scripts/demo_ios.py

  # Or let the adapter boot tart automatically:
  python scripts/demo_ios.py

Walks through the full Inspector loop on the iOS surface:
  1. Boot simulator (via MacOSPlane over SSH)
  2. Build + install the sample-buggy-ios app
  3. Screenshot -> observe elements
  4. Tap the "Save" button
  5. Detect the crash (index out of range)
  6. Tear down
"""
from __future__ import annotations

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inspector.config import Config
from inspector.adapters.ios import IOSAdapter
from inspector.adapters.base import InputAction
from inspector.models import ActionType


def main():
    print("=== Inspector iOS Demo ===\n")

    host = os.getenv("LOOPBACK_MACOS_HOST")
    if host:
        print(f"Using macOS host: {host}")
    else:
        print("No LOOPBACK_MACOS_HOST set — will try to boot tart VM automatically.")

    config = Config.from_env()
    adapter = IOSAdapter(config)

    repo_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples", "sample-buggy-ios",
    )
    print(f"Sample app: {repo_path}\n")

    # --- Step 1: Launch ---
    print("[1/6] Launching (boot sim + build + install) ...")
    try:
        adapter.launch(repo_path)
    except Exception as e:
        print(f"  ERROR during launch: {e}")
        print("  Make sure the VM is provisioned (run infra/macos-tart/provision-vm.sh)")
        adapter.teardown()
        sys.exit(1)

    # --- Step 2: Wait for ready ---
    print("[2/6] Waiting for app to be ready ...")
    ready = adapter.is_ready(timeout_s=60)
    if not ready:
        print("  App did not become ready within 60s.")
        adapter.teardown()
        sys.exit(1)
    print("  App is ready.\n")

    # --- Step 3: Screenshot ---
    print("[3/6] Taking screenshot ...")
    png = adapter.screenshot()
    screenshot_path = "/tmp/inspector_ios_demo.png"
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
    # The Save button is roughly centered horizontally, below the text field.
    # On iPhone 15 (393x852), it's approximately at (196, 460).
    # But we'll use a rough center-screen tap — in a real run, the detector
    # would identify the button's coordinates.
    tap_x = w // 2
    tap_y = int(h * 0.54)  # approximate Save button position
    print(f"[5/6] Tapping 'Save' button at ({tap_x}, {tap_y}) ...")
    adapter.input(InputAction(type=ActionType.CLICK, x=tap_x, y=tap_y))
    time.sleep(2)

    # Screenshot after tap
    png_after = adapter.screenshot()
    after_path = "/tmp/inspector_ios_demo_after.png"
    with open(after_path, "wb") as f:
        f.write(png_after)
    print(f"  Post-tap screenshot: {after_path}")

    # Check for crash
    print()
    print("[6/6] Checking for crash ...")
    logs_after = adapter.logs()
    crash_found = False
    for line in logs_after:
        if any(kw in line.lower() for kw in ["crash", "fatal", "index out of range", "exception"]):
            crash_found = True
        print(f"  {line}")

    print()
    if crash_found:
        print("CRASH DETECTED — the Save button triggers 'Fatal error: Index out of range'.")
        print("This is the bug Inspector is designed to catch and report back to the agent.")
    else:
        print("No crash in logs (the app may have crashed silently — check crash reports).")
        # Try crash reports
        crash_lines = adapter._check_crash_reports()
        if crash_lines:
            print("Found crash report:")
            for line in crash_lines[:10]:
                print(f"  {line}")

    # --- Teardown ---
    print("\nTearing down ...")
    adapter.teardown()
    print("Done.\n")

    print("=== Demo complete ===")
    print(f"Screenshots: {screenshot_path}, {after_path}")


if __name__ == "__main__":
    main()
