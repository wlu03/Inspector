"""Pure tests for the Android adapter — no device, no Redroid.

Covers adb command construction (local + SSH), the input→adb mapping via a fake
transport, and the uiautomator/wm-size/keycode parsers.
"""
from __future__ import annotations

from inspector.adapters.android import (
    AndroidAdapter,
    escape_text,
    keycode,
    parse_uiautomator_labels,
    parse_wm_size,
)
from inspector.adb import AdbTransport
from inspector.config import Config
from inspector.models import ActionType
from inspector.adapters.base import InputAction


# --- AdbTransport argv (pure) ---

def test_local_argv():
    t = AdbTransport(serial="localhost:5555")
    assert t.build_argv(["shell", "input tap 1 2"]) == [
        "adb", "-s", "localhost:5555", "shell", "input tap 1 2",
    ]


def test_ssh_argv_wraps_adb_as_remote_command():
    t = AdbTransport(serial="emulator-5554", ssh_host="host", ssh_user="ubuntu", ssh_key="/k")
    argv = t.build_argv(["exec-out", "screencap -p"])
    assert argv[:2] == ["ssh", "-o"]
    assert "-i" in argv and "/k" in argv and "ubuntu@host" in argv
    # the whole adb command travels as one quoted remote arg
    assert argv[-1] == "adb -s emulator-5554 exec-out 'screencap -p'"


# --- input → adb command mapping (fake transport records shell calls) ---

class _FakeAdb:
    def __init__(self):
        self.calls: list[str] = []

    def shell(self, cmd, timeout=60):
        self.calls.append(cmd)
        return ""

    def exec_out(self, cmd, timeout=60):
        self.calls.append(cmd)
        return b"PNGBYTES"

    def logcat(self, buffers="crash,main", pid=None, timeout=30):
        return "F/libc: Fatal signal 11\nI/Chatty: ok\n"


def _adapter():
    a = AndroidAdapter(Config(), adb=_FakeAdb())
    a._size = (1080, 1920)
    return a


def test_click_taps_at_coords():
    a = _adapter()
    a.input(InputAction(ActionType.CLICK, x=540, y=960))
    assert a.adb.calls == ["input tap 540 960"]


def test_double_click_taps_twice():
    a = _adapter()
    a.input(InputAction(ActionType.DOUBLE_CLICK, x=10, y=20))
    assert a.adb.calls == ["input tap 10 20", "input tap 10 20"]


def test_type_escapes_spaces():
    a = _adapter()
    a.input(InputAction(ActionType.TYPE, text="hello world"))
    assert a.adb.calls == ["input text hello%sworld"]


def test_key_maps_to_keyevent():
    a = _adapter()
    a.input(InputAction(ActionType.KEY, key="Return"))
    assert a.adb.calls == ["input keyevent 66"]


def test_scroll_swipes_from_center():
    a = _adapter()
    a.input(InputAction(ActionType.SCROLL, direction="down"))
    assert a.adb.calls == ["input swipe 540 960 540 360 300"]


def test_screenshot_uses_exec_out_screencap():
    a = _adapter()
    assert a.screenshot() == b"PNGBYTES"
    assert a.adb.calls == ["screencap -p"]


def test_logs_filters_blank_lines():
    a = _adapter()
    assert a.logs() == ["F/libc: Fatal signal 11", "I/Chatty: ok"]


def test_filter_app_logs_keeps_app_and_crashes():
    from inspector.adapters.android import filter_app_logs
    lines = [
        "E ctbc: NullPointerException in some.other.app",       # background noise → dropped
        "E Inspector: query not invalidated  com.inspector.sample",  # our package → kept
        "E AndroidRuntime: FATAL EXCEPTION: main",              # crash marker → kept
        "I Chatty: unrelated",                                  # noise → dropped
    ]
    out = filter_app_logs(lines, "com.inspector.sample")
    assert len(out) == 2
    assert any("com.inspector.sample" in ln for ln in out)
    assert any("AndroidRuntime" in ln for ln in out)


def test_wake_keeps_screen_on():
    a = _adapter()
    a._wake()
    assert "svc power stayon true" in a.adb.calls
    assert any("KEYCODE_WAKEUP" in c for c in a.adb.calls)
    assert any("dismiss-keyguard" in c for c in a.adb.calls)


# --- LOW-c: DRAG must not interpolate None into the shell string ---

def test_drag_with_missing_endpoints_is_noop():
    a = _adapter()
    a.input(InputAction(ActionType.DRAG, x=10, y=20))  # to_x/to_y default None
    assert a.adb.calls == []  # no "input swipe 10 20 None None 300"


def test_drag_swipes_when_endpoints_present():
    a = _adapter()
    a.input(InputAction(ActionType.DRAG, x=10, y=20, to_x=30, to_y=40))
    assert a.adb.calls == ["input swipe 10 20 30 40 300"]


# --- #3a: adb run() surfaces real failures, stays quiet on benign non-zero ---

class _CP:
    def __init__(self, rc, out=b"", err=b""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_adb_run_warns_on_real_failure(monkeypatch, caplog):
    from inspector import adb as adbmod
    monkeypatch.setattr(adbmod.subprocess, "run", lambda *a, **k: _CP(1, b"", b"adb: device offline"))
    t = AdbTransport(serial="x")
    with caplog.at_level("WARNING", logger="inspector"):
        out = t.shell("dumpsys activity")
    assert out == ""  # still returns (empty) stdout — callers unchanged
    assert any("device offline" in r.getMessage() for r in caplog.records)


def test_adb_run_silent_on_benign_nonzero(monkeypatch, caplog):
    # grep with no match -> returncode 1, empty stderr: NOT a failure, must not warn.
    from inspector import adb as adbmod
    monkeypatch.setattr(adbmod.subprocess, "run", lambda *a, **k: _CP(1, b"", b""))
    t = AdbTransport(serial="x")
    with caplog.at_level("WARNING", logger="inspector"):
        t.shell("ps | grep nothing")
    assert not any("failed" in r.getMessage() for r in caplog.records)


# --- parsers (pure) ---

def test_keycode_known_and_numeric_and_unknown():
    assert keycode("Return") == 66
    assert keycode("82") == 82
    assert keycode("Nonsense") is None
    assert keycode(None) is None


def test_escape_text_quotes_and_spaces():
    assert escape_text("a b") == "a%sb"          # no shell-special chars → no quoting
    assert escape_text("a&b") == "'a&b'"         # shell-special → quoted


def test_parse_wm_size_prefers_override():
    assert parse_wm_size("Physical size: 1080x1920\nOverride size: 720x1280") == (720, 1280)
    assert parse_wm_size("Physical size: 1080x1920") == (1080, 1920)
    assert parse_wm_size("garbage") is None


_UIA = """\
UI hierarchy dumped to: /sdcard/ui.xml
<?xml version='1.0'?>
<hierarchy rotation="0">
  <node class="android.widget.TextView" text="Settings" clickable="false"/>
  <node class="android.widget.Button" text="Save" clickable="true"/>
  <node class="android.widget.EditText" text="" content-desc="Your name" clickable="true"/>
  <node class="android.view.View" text="" clickable="false"/>
  <node class="android.widget.Button" text="Save" clickable="true"/>
</hierarchy>
"""


def test_parse_uiautomator_labels():
    labels = parse_uiautomator_labels(_UIA)
    # interactive only, de-duped, text or content-desc; the TextView is skipped
    assert labels == ["Save", "Your name"]


def test_parse_uiautomator_handles_garbage():
    assert parse_uiautomator_labels("not xml at all") == []
    assert parse_uiautomator_labels("") == []


# --- local emulator runtime (pure helpers) ---

def test_emulator_argv_is_headless_ephemeral():
    from inspector.planes.android import emulator_argv
    argv = emulator_argv("/sdk/emulator", "inspector", port=5554)
    assert argv[:5] == ["/sdk/emulator", "-avd", "inspector", "-port", "5554"]
    assert "-no-snapshot-save" in argv  # ephemeral
    assert "swiftshader_indirect" in argv  # software GL, works headless


def test_parse_avd_list_skips_warnings():
    from inspector.planes.android import parse_avd_list
    out = "INFO | Storage...\ninspector\nPixel_7_API_34\n"
    assert parse_avd_list(out) == ["inspector", "Pixel_7_API_34"]


def test_local_runtime_serial_matches_port():
    from inspector.planes.android import LocalEmulatorRuntime
    rt = LocalEmulatorRuntime(Config(), avd="inspector", port=5556)
    assert rt.serial == "emulator-5556"


def test_android_adapter_defaults_to_local_transport():
    # default runtime is local → adb transport has no ssh host
    a = AndroidAdapter(Config())
    t = a._make_transport("emulator-5554")
    assert t.ssh_host is None and t.serial == "emulator-5554"
