"""Pure tests for the web adapter's browser-launch + readiness helpers.

These import the adapter module (SDK-free) and exercise the pure functions that
gate the Chrome-launch fix — no sandbox required.
"""
from __future__ import annotations

import json

from inspector.adapters.web import (
    CDP_PORT,
    _is_app_window,
    cdp_page_ready,
    chrome_launch_cmd,
    pick_browser,
)


# --- browser resolution ---

def test_pick_browser_prefers_google_chrome():
    assert pick_browser({"chromium", "google-chrome"}) == "google-chrome"


def test_pick_browser_falls_through_to_chromium():
    assert pick_browser({"chromium-browser"}) == "chromium-browser"


def test_pick_browser_none_when_only_firefox():
    # Firefox isn't a candidate (no CDP) → must report "no browser".
    assert pick_browser({"firefox"}) is None
    assert pick_browser(set()) is None


# --- launch command ---

def test_chrome_launch_cmd_has_cdp_and_app_url():
    cmd = chrome_launch_cmd("google-chrome", "http://localhost:5173/")
    assert "--app=http://localhost:5173/" in cmd
    assert f"--remote-debugging-port={CDP_PORT}" in cmd
    assert "google-chrome " in cmd
    # the two flags that make CDP actually come up in the sandbox (verified live)
    assert "DISPLAY=:0" in cmd
    assert "--disable-dev-shm-usage" in cmd


# --- CDP readiness gate (the core false-positive fix) ---

def test_cdp_ready_true_with_page_target():
    payload = json.dumps([
        {"type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/X"},
    ])
    assert cdp_page_ready(payload) is True


def test_cdp_ready_false_when_no_page_target():
    # service_worker / background only — not an inspectable page yet.
    payload = json.dumps([{"type": "service_worker", "webSocketDebuggerUrl": "ws://x"}])
    assert cdp_page_ready(payload) is False


def test_cdp_ready_false_on_empty_or_garbage():
    assert cdp_page_ready("") is False
    assert cdp_page_ready("not json") is False
    assert cdp_page_ready("[]") is False


# --- window filter (don't lock the crop onto Firefox/desktop) ---

def test_app_window_accepts_real_title():
    assert _is_app_window("Sample Buggy App") is True


def test_app_window_rejects_firefox_and_desktop():
    assert _is_app_window("Mozilla Firefox") is False
    assert _is_app_window("Desktop") is False
    assert _is_app_window("") is False
