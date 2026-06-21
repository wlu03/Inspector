import json

from inspector.adapters.ios import (
    IOSAdapter,
    first_iphone_udid,
    first_scheme,
    idb_swipe_cmd,
    idb_tap_cmd,
    idb_text_cmd,
    ios_build_command,
    locate_app_command,
    merge_elements,
    parse_describe_all,
    parse_screen_points,
)
from inspector.adapters.base import InputAction
from inspector.config import Config
from inspector.launch.detect import detect_project
from inspector.models import ActionType, Element
from inspector.planes.macos import RunResult, decode_screenshot, scp_argv, ssh_argv


# ---------- MacOSPlane pure helpers ----------

def test_ssh_scp_argv():
    a = ssh_argv("admin", "1.2.3.4", "echo hi", ssh_key="/k")
    assert a[0] == "ssh" and a[-2] == "admin@1.2.3.4" and a[-1] == "echo hi" and "/k" in a
    s = scp_argv("admin", "1.2.3.4", "/local", "/remote", ssh_key="/k")
    assert s[0] == "scp" and "-r" in s and s[-1] == "admin@1.2.3.4:/remote"


def test_decode_screenshot():
    import base64
    assert decode_screenshot(base64.b64encode(b"PNGDATA").decode()) == b"PNGDATA"
    assert decode_screenshot("not base64 @@@") == b"" or isinstance(decode_screenshot("x"), bytes)


# ---------- point-vs-pixel + a11y parsing ----------

def test_parse_screen_points_prefers_points():
    j = json.dumps({"screen_dimensions": {"width": 1179, "height": 2556, "density": 3.0,
                                          "width_points": 393, "height_points": 852}})
    assert parse_screen_points(j) == (393, 852)


def test_parse_screen_points_from_density():
    j = json.dumps({"screen_dimensions": {"width": 1170, "height": 2532, "density": 3.0}})
    assert parse_screen_points(j) == (390, 844)


def test_parse_screen_points_fallback():
    assert parse_screen_points("garbage") == (393, 852)


def test_parse_describe_all_normalizes_to_point_ratios():
    nodes = [
        {"frame": {"x": 100, "y": 200, "width": 80, "height": 40}, "AXLabel": "Save",
         "type": "Button", "enabled": True},
        {"AXFrame": "{{0, 0}, {393, 60}}", "AXLabel": "Title", "type": "StaticText", "enabled": True},
        {"frame": {"x": 0, "y": 0, "width": 0, "height": 0}, "type": "Button"},  # degenerate → skipped
    ]
    els = parse_describe_all(json.dumps(nodes), 393, 852)
    assert len(els) == 2
    save = els[0]
    assert save.label == "Save" and save.role == "button" and save.interactivity is True
    assert save.source == "a11y"
    assert abs(save.bbox[0] - 100 / 393) < 1e-6 and abs(save.bbox[2] - 180 / 393) < 1e-6
    assert els[1].interactivity is False  # static text


def test_point_vs_pixel_contract_center_maps_to_points():
    # an a11y button at point rect (100,200,80x40) on a 393x852 POINT screen
    els = parse_describe_all(json.dumps([
        {"frame": {"x": 100, "y": 200, "width": 80, "height": 40}, "AXLabel": "Save",
         "type": "Button", "enabled": True}]), 393, 852)
    # center_px with POINT screen_size must land the idb tap at the point center (140, 220)
    assert els[0].center_px(393, 852) == (140, 220)


def test_merge_appends_non_overlapping_vision():
    a11y = [Element(id=0, label="Btn", role="button", bbox=[0.0, 0.0, 0.2, 0.1], interactivity=True, source="a11y")]
    vision = [
        Element(id=0, label="overlap", role="icon", bbox=[0.01, 0.01, 0.19, 0.09], interactivity=True),  # IoU high → dropped
        Element(id=1, label="webview-btn", role="icon", bbox=[0.5, 0.5, 0.7, 0.6], interactivity=True),   # distinct → kept
    ]
    merged = merge_elements(a11y, vision)
    labels = {e.label for e in merged}
    assert "Btn" in labels and "webview-btn" in labels and "overlap" not in labels
    assert [e.id for e in merged] == list(range(len(merged)))  # renumbered


# ---------- udid + build commands ----------

def test_first_iphone_udid():
    j = json.dumps({"devices": {"iOS-17": [
        {"name": "iPad", "udid": "ipad-1", "isAvailable": True},
        {"name": "iPhone 15", "udid": "iphone-1", "isAvailable": True},
    ]}})
    assert first_iphone_udid(j) == "iphone-1"
    assert first_iphone_udid("garbage") is None


def test_build_commands_per_kit():
    assert "xcodebuild" in ios_build_command("apple-native")
    assert "flutter build ios" in ios_build_command("flutter")
    assert "run-ios" in ios_build_command("expo") or "run:ios" in ios_build_command("expo")


def test_locate_app_command_per_framework():
    assert "build/ios" in locate_app_command("flutter")          # flutter output
    assert "ios/build" in locate_app_command("react-native")     # RN run-ios output
    assert "$PWD/build" in locate_app_command("apple-native") and "ios/build" not in locate_app_command("apple-native")


def test_first_scheme():
    assert first_scheme(json.dumps({"project": {"schemes": ["SampleBuggyApp", "Other"]}})) == "SampleBuggyApp"
    assert first_scheme(json.dumps({"workspace": {"schemes": ["WS"]}})) == "WS"
    assert first_scheme("garbage") is None


def test_idb_command_builders():
    assert idb_tap_cmd("idb", "UD", 10, 20) == "idb ui tap --udid UD 10 20"
    assert "idb ui text --udid UD" in idb_text_cmd("idb", "UD", "hi")
    assert idb_swipe_cmd("idb", "UD", 1, 2, 3, 4) == "idb ui swipe --udid UD 1 2 3 4"
    assert idb_tap_cmd("/v/bin/idb", "UD", 1, 2) == "/v/bin/idb ui tap --udid UD 1 2"


# ---------- adapter wiring (fake plane) ----------

class _FakePlane:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def run_sync(self, cmd, timeout=120):
        self.calls.append(cmd)
        for key, val in self.responses.items():
            if key in cmd:
                return val if isinstance(val, RunResult) else RunResult(val, "", 0)
        return RunResult("", "", 0)

    def run_bg(self, cmd):
        self.calls.append(("bg", cmd))

    def screenshot(self):
        return b"PNG"

    def start(self): pass
    def stop(self): pass
    def upload(self, a, b): pass


def _adapter(responses=None):
    a = IOSAdapter(Config())
    a.plane = _FakePlane(responses)
    a.udid = "UDID"
    a._point_size = (393, 852)
    return a


def test_screen_size_returns_points():
    assert _adapter().screen_size() == (393, 852)


def test_input_click_and_type_map_to_idb():
    a = _adapter()
    a.input(InputAction(ActionType.CLICK, x=140, y=220))
    assert "idb ui tap --udid UDID 140 220" in a.plane.calls
    a.input(InputAction(ActionType.TYPE, x=50, y=60, text="Alice"))
    # type focuses first (tap) then sends text
    assert any("idb ui tap --udid UDID 50 60" in c for c in a.plane.calls)
    assert any("idb ui text --udid UDID" in c and "Alice" in c for c in a.plane.calls)


def test_log_capture_scoped_to_app_process():
    a = _adapter()
    a._app_process = "SampleBuggyApp"
    a._start_log_capture()
    bg = [c for c in a.plane.calls if isinstance(c, tuple) and c[0] == "bg"]
    assert bg and 'process == "SampleBuggyApp"' in bg[-1][1]


def test_detect_elements_uses_a11y_then_none_when_idb_down():
    nodes = [
        {"frame": {"x": 10, "y": 10, "width": 80, "height": 40}, "AXLabel": "A", "type": "Button", "enabled": True},
        {"frame": {"x": 10, "y": 80, "width": 80, "height": 40}, "AXLabel": "B", "type": "Button", "enabled": True},
    ]
    a = _adapter({"describe-all": json.dumps(nodes)})
    els = a.detect_elements(b"PNG")
    assert els is not None and len(els) == 2 and els[0].source == "a11y"

    # idb returns nothing → fall back to OmniParser (None)
    a2 = _adapter({"describe-all": ""})
    assert a2.detect_elements(b"PNG") is None


# ---------- native project detection + config ----------

def test_detect_native_xcode(tmp_path):
    (tmp_path / "App.xcodeproj").mkdir()
    p = detect_project(str(tmp_path))
    assert p.framework == "apple-native" and p.surface.value == "ios"


def test_detect_native_flutter(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: app\n")
    assert detect_project(str(tmp_path)).framework == "flutter"


def test_detect_flutter_wins_over_nested_xcodeproj(tmp_path):
    # a real Flutter project has pubspec.yaml at root AND ios/Runner.xcodeproj —
    # the recursive xcodeproj glob must not misclassify it as apple-native.
    (tmp_path / "pubspec.yaml").write_text("name: app\n")
    (tmp_path / "ios").mkdir()
    (tmp_path / "ios" / "Runner.xcodeproj").mkdir()
    p = detect_project(str(tmp_path))
    assert p.framework == "flutter" and p.surface.value == "ios"


def test_config_macos_env(monkeypatch):
    monkeypatch.setenv("INSPECTOR_MACOS_HOST", "10.0.0.5")
    monkeypatch.setenv("INSPECTOR_IOS_UDID", "abc-123")
    cfg = Config.from_env()
    assert cfg.macos_host == "10.0.0.5" and cfg.macos_ios_udid == "abc-123" and cfg.macos_user == "admin"


# ---------- local execution mode (runs on THIS host, no VM) ----------

def test_macos_plane_local_runs_on_host():
    from inspector.planes.macos import MacOSPlane
    p = MacOSPlane(local=True)
    p.start()  # no-op (no tart)
    r = p.run_sync("echo inspector-local")  # real subprocess on the host
    assert r is not None and "inspector-local" in r.stdout and r.exit_code == 0
    p.upload("/nonexistent", "/whatever")  # no-op in local, must not raise
    p.stop()  # no tart delete


def test_ios_adapter_local_vs_vm():
    assert IOSAdapter(Config(execution="local")).plane.local is True
    assert IOSAdapter(Config(execution="vm", macos_host="1.2.3.4")).plane.local is False


def test_execution_defaults_local():
    assert Config().execution == "local"
