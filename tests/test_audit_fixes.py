"""Tests for the audit-driven fixes."""
from __future__ import annotations

import json

from inspector.android_build import pick_newest
from inspector.detection import scan_logs
from inspector.driver import Decision, FallbackDriver
from inspector.expectations import ExpectedElement, diff_expected_vs_actual
from inspector.launch.detect import detect_project
from inspector.models import Confidence, Severity, Surface


# --- detection markers (no longer flags benign "error" copy) ---

def test_benign_error_words_not_flagged():
    for line in ["No errors found", "errorRate: 0", "clearError() called",
                 "E SampleBuggyApp[1:2] (CoreHaptics) CHHapticPattern loaded"]:
        assert scan_logs([line]) == [], line


def test_real_errors_still_flagged_with_right_confidence():
    high = scan_logs(["Uncaught TypeError: cannot read 'x' of undefined"])
    assert len(high) == 1 and high[0].severity == Severity.HIGH
    assert high[0].confidence == Confidence.HIGH

    med = scan_logs(["[console.error] query not invalidated"])
    assert len(med) == 1 and med[0].severity == Severity.MEDIUM
    assert med[0].confidence == Confidence.MEDIUM  # no longer hardcoded HIGH

    crit = scan_logs(["FATAL EXCEPTION: main"])
    assert crit and crit[0].severity == Severity.CRITICAL


# --- FallbackDriver now falls back on an exception, not just a degenerate decision ---

class _BoomDriver:
    def decide(self, *a):
        raise RuntimeError("token limit")


class _HeuristicStub:
    def decide(self, *a):
        return Decision(action="click", target_id=0, reason="heuristic")


def test_fallback_on_driver_exception():
    d = FallbackDriver(_BoomDriver(), _HeuristicStub()).decide(b"", [], "g", [], [])
    assert d.action == "click" and d.reason == "heuristic"


# --- expectations: short labels no longer spuriously "present" ---

def test_short_label_not_false_matched():
    missing = diff_expected_vs_actual(
        [ExpectedElement("ok", "button", "a:1"), ExpectedElement("Save", "button", "a:2")],
        ["Bookmarks", "Save settings"],  # "ok" ⊂ "Bookmarks" but is too short to count
    )
    assert [m.label for m in missing] == ["ok"]  # "ok" missing; "Save" matched "Save settings"


# --- android_build: never installs the instrumentation APK ---

def test_pick_newest_excludes_androidtest(tmp_path):
    real = tmp_path / "app-debug.apk"
    test = tmp_path / "app-debug-androidTest.apk"
    real.write_text("a")
    test.write_text("b")
    import os
    os.utime(test, (os.path.getmtime(real) + 100,) * 2)  # make the test APK newer
    assert pick_newest([str(test), str(real)]) == str(real)


# --- launch detection: bare React Native gets a mobile surface ---

def test_bare_react_native_detected(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps(
        {"dependencies": {"react-native": "0.74"}, "scripts": {"start": "react-native start"}}))
    info = detect_project(str(tmp_path))
    assert info.framework == "react-native" and info.surface == Surface.ANDROID


# --- replay: '<' fully escaped so finding text can't break out of <script> ---

def test_replay_escapes_all_angle_brackets():
    from inspector.replay import _build_html
    sess = {"id": "s", "surface": "web", "goal": "", "state": "x"}
    findings = [{"summary": "<!--</script><img src=x onerror=alert(1)>", "severity": "high",
                 "confidence": "high", "screenshot_refs": ["frame_0000.png"], "bbox": []}]
    html = _build_html(sess, ["frame_0000.png"], [], findings)
    # the raw injection sequence must not survive verbatim inside the <script> data
    assert "</script><img" not in html
    assert "\\u003c" in html  # angle brackets escaped in the JSON blob
