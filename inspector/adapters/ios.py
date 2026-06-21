from __future__ import annotations

import json
import shlex

from ..config import Config
from ..models import ActionType, Element, Surface
from ..planes.macos import MacOSPlane
from .base import InputAction, SurfaceAdapter

# Roles (lowercased, AX-prefix-stripped) that count as interactive for the a11y tree.
_INTERACTIVE_ROLES = {
    "button", "textfield", "securetextfield", "searchfield", "switch", "cell",
    "link", "slider", "stepper", "segmentedcontrol", "tab", "tabbar", "menuitem",
    "checkbox", "radiobutton", "textview", "picker", "pickerwheel", "keyboard",
    "popupbutton", "image",
}
# HID usage codes for `idb ui key`.
_HID_KEYS = {
    "enter": 40, "return": 40, "tab": 43, "space": 44, "delete": 42,
    "backspace": 42, "escape": 41, "up": 82, "down": 81, "left": 80, "right": 79,
}
_A11Y_MIN_INTERACTIVE = 2  # below this, the tree is opaque (webview/canvas) → merge vision
_DEFAULT_POINTS = (393, 852)  # iPhone 15-class default until idb describe refines it


# ---------------- pure helpers (unit-tested) ----------------

def ios_build_command(framework: str, flutter_bin: str = "flutter") -> str:
    """Build command (run in the remote app dir) for the simulator build."""
    if framework == "flutter":
        return f"{flutter_bin} build ios --simulator --debug"
    if framework in ("expo", "react-native", "rn"):
        return "npx react-native run-ios --simulator 2>/dev/null || npx expo run:ios"
    # apple-native (xcodeproj / Package.swift): xcodebuild auto-detects the project
    return (
        "xcodebuild -sdk iphonesimulator -configuration Debug "
        "-derivedDataPath ./build CODE_SIGNING_ALLOWED=NO build"
    )


def locate_app_command(framework: str) -> str:
    """Shell command that prints the built .app path (first match).

    Emits an ABSOLUTE path ($PWD) — later install/plutil commands run in a fresh
    subprocess without the build dir as cwd, so a relative ./build path would break.
    Output dir differs per framework: flutter → build/ios; RN → ios/build (run-ios
    self-installs, but we still locate the .app to read its bundle id); else ./build.
    """
    if framework == "flutter":
        root = "$PWD/build/ios"
    elif framework in ("expo", "react-native", "rn"):
        root = "$PWD/ios/build $PWD/build"
    else:
        root = "$PWD/build"
    return f"find {root} -maxdepth 6 -name '*.app' -type d 2>/dev/null | head -1"


def first_scheme(list_json: str) -> str | None:
    """First scheme from `xcodebuild -list -json`. Pure.

    xcodebuild needs -scheme when -derivedDataPath is set; the scheme is project-
    specific (= the xcodegen target name), so we detect it rather than guess.
    """
    try:
        d = json.loads(list_json)
        for key in ("project", "workspace"):
            schemes = (d.get(key) or {}).get("schemes") or []
            if schemes:
                return schemes[0]
    except Exception:
        pass
    return None


def parse_screen_points(describe_json: str) -> tuple[int, int]:
    """Device POINT dimensions from `idb describe --json`. Pure.

    Critical for the point-vs-pixel contract: idb taps use POINTS, simctl screenshots
    are PIXELS. screen_size() must return points so ratio*size lands a correct tap.
    """
    try:
        d = json.loads(describe_json)
        sd = d.get("screen_dimensions") or d.get("screen") or {}
        wp, hp = sd.get("width_points"), sd.get("height_points")
        if wp and hp:
            return int(wp), int(hp)
        w, h, dens = sd.get("width"), sd.get("height"), sd.get("density") or 1
        if w and h and dens:
            return int(w / dens), int(h / dens)
    except Exception:
        pass
    return _DEFAULT_POINTS


def first_iphone_udid(list_devices_json: str) -> str | None:
    """First available iPhone simulator UDID from `simctl list devices available -j`."""
    try:
        data = json.loads(list_devices_json)
        for _runtime, devices in (data.get("devices") or {}).items():
            for dev in devices:
                if dev.get("isAvailable", True) and "iPhone" in (dev.get("name") or ""):
                    return dev.get("udid")
    except Exception:
        pass
    return None


def _frame_of(node: dict) -> tuple[float, float, float, float] | None:
    """Extract (x, y, w, h) in points from an idb a11y node, defensively."""
    fr = node.get("frame")
    if isinstance(fr, dict):
        try:
            return float(fr["x"]), float(fr["y"]), float(fr["width"]), float(fr["height"])
        except (KeyError, TypeError, ValueError):
            pass
    ax = node.get("AXFrame")  # "{{x, y}, {w, h}}"
    if isinstance(ax, str):
        nums = [t for t in ax.replace("{", " ").replace("}", " ").replace(",", " ").split() if t]
        try:
            x, y, w, h = (float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3]))
            return x, y, w, h
        except (IndexError, ValueError):
            pass
    return None


def parse_describe_all(describe_all_json: str, w_pts: int, h_pts: int) -> list[Element]:
    """Parse `idb ui describe-all --json` into Element[] (bbox as 0..1 point-ratios). Pure."""
    try:
        nodes = json.loads(describe_all_json)
    except Exception:
        return []
    if not isinstance(nodes, list) or not w_pts or not h_pts:
        return []
    out: list[Element] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        frame = _frame_of(node)
        if frame is None:
            continue
        x, y, w, h = frame
        if w <= 0 or h <= 0:
            continue
        label = (node.get("AXLabel") or node.get("AXValue") or node.get("title")
                 or node.get("help") or "")
        role = str(node.get("type") or node.get("role_description") or node.get("role") or "")
        role = role.lower().replace("ax", "").strip()
        enabled = bool(node.get("enabled", True))
        interactive = enabled and (role in _INTERACTIVE_ROLES)
        out.append(Element(
            id=0, label=str(label).strip(), role=role,
            bbox=[x / w_pts, y / h_pts, (x + w) / w_pts, (y + h) / h_pts],
            interactivity=interactive, source="a11y",
        ))
    return out


def describe_value_at(describe_all_json: str, index: int) -> dict:
    """The AXValue/AXLabel of the element at `index` (same filter/order as
    parse_describe_all) — the live VALUE for the input-integrity oracle. Pure."""
    try:
        nodes = json.loads(describe_all_json)
    except Exception:
        return {}
    if not isinstance(nodes, list):
        return {}
    valid = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        frame = _frame_of(node)
        if frame is None or frame[2] <= 0 or frame[3] <= 0:
            continue
        valid.append(node)
    if 0 <= index < len(valid):
        n = valid[index]
        return {
            "value": str(n.get("AXValue") or ""),
            "label": str(n.get("AXLabel") or ""),
            "role": str(n.get("type") or n.get("role") or ""),
        }
    return {}


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def merge_elements(a11y: list[Element], vision: list[Element], iou_thresh: float = 0.3) -> list[Element]:
    """Keep all a11y elements; append vision elements that don't overlap one. Pure."""
    merged = list(a11y)
    for v in vision:
        if not any(_iou(v.bbox, e.bbox) > iou_thresh for e in a11y):
            merged.append(v)
    return _renumber(merged)


def _renumber(els: list[Element]) -> list[Element]:
    for i, e in enumerate(els):
        e.id = i
    return els


def idb_tap_cmd(idb: str, udid: str, x: int, y: int) -> str:
    return f"{idb} ui tap --udid {shlex.quote(udid)} {x} {y}"


def idb_text_cmd(idb: str, udid: str, text: str) -> str:
    return f"{idb} ui text --udid {shlex.quote(udid)} {shlex.quote(text)}"


def idb_swipe_cmd(idb: str, udid: str, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> str:
    # --duration makes the swipe a deterministic drag, not a momentum flick.
    return f"{idb} ui swipe --udid {shlex.quote(udid)} {x1} {y1} {x2} {y2} --duration {duration}"


def idb_key_cmd(idb: str, udid: str, code: int) -> str:
    return f"{idb} ui key --udid {shlex.quote(udid)} {code}"


# ---------------- the adapter ----------------

class IOSAdapter(SurfaceAdapter):
    """iOS apps via the Simulator inside a tart macOS VM (simctl + idb over SSH).

    Grounding is hybrid: native a11y tree (idb describe-all) primary, OmniParser SoM
    fallback for opaque webview/canvas screens. Clicks always go through pixels
    (Element.center_px), so the pure-computer-use action path is unchanged.
    """

    surface = Surface.IOS
    REMOTE_APP_DIR = "/tmp/inspector-app"
    LOG_FILE = "/tmp/inspector_ios.log"

    def __init__(self, config: Config):
        self.config = config
        self.plane = MacOSPlane(
            base_image=config.macos_base_image, host=config.macos_host,
            user=config.macos_user, ssh_key=config.macos_ssh_key,
            local=(config.execution == "local"),
        )
        self.udid: str | None = config.macos_ios_udid
        self.bundle_id: str | None = None
        self._idb = config.ios_idb_bin  # idb client binary (py3.10-3.12; not 3.14)
        self._flutter_bin = config.flutter_bin  # flutter binary for Flutter builds
        self._app_dir: str | None = None
        self._app_process: str | None = None  # executable name → log-stream predicate
        self._point_size: tuple[int, int] = _DEFAULT_POINTS
        self._log_seen = 0
        self._detector = None  # lazy OmniParser, only for the webview fallback-merge
        self.project = None

    # --- lifecycle ---
    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.plane.start()
        self.project = _detect_ios_project(repo_path)
        if self.plane.local:
            self._app_dir = repo_path  # build in place on the host — no upload
        else:
            self.plane.run_sync(f"rm -rf {self.REMOTE_APP_DIR}", timeout=30)
            self.plane.upload(repo_path, self.REMOTE_APP_DIR)
            self._app_dir = self.REMOTE_APP_DIR
        self._ensure_device()
        # build the app for the simulator (scheme-aware for apple-native projects)
        if dev_command:
            build = dev_command
        elif self.project.framework == "apple-native":
            build = self._apple_build_cmd(self._app_dir)
        else:
            build = ios_build_command(self.project.framework, self._flutter_bin)
        self.plane.run_sync(
            f"cd {shlex.quote(self._app_dir)} && {build}", timeout=1200,
        )
        # locate + install + launch (skip when the builder already installs, e.g. RN)
        r = self.plane.run_sync(
            f"cd {shlex.quote(self._app_dir)} && {locate_app_command(self.project.framework)}", timeout=30,
        )
        app_path = (r.stdout.strip() if r and r.stdout else "")
        if app_path:
            self.plane.run_sync(
                f"xcrun simctl install {self.udid} {shlex.quote(app_path)}", timeout=180,
            )
            self.bundle_id = self._bundle_id_of(app_path)
            # process name = CFBundleExecutable (the .app dir name differs for RN /
            # renamed / spaces-in-name apps, which would make the log predicate match
            # nothing); fall back to the bundle basename if the plist read fails.
            self._app_process = (self._app_executable(app_path)
                                 or app_path.rsplit("/", 1)[-1].removesuffix(".app"))
            if self.bundle_id:
                self.plane.run_sync(
                    f"xcrun simctl launch {self.udid} {shlex.quote(self.bundle_id)}", timeout=60,
                )

    def is_ready(self, timeout_s: float = 180.0) -> bool:
        if not self.udid:
            return False
        # block until the device is fully booted
        self.plane.run_sync(f"xcrun simctl bootstatus {self.udid} -b", timeout=int(timeout_s))
        # refine the point size from idb (the point-vs-pixel contract)
        r = self.plane.run_sync(f"{self._idb} describe --udid {self.udid} --json", timeout=30)
        if r and r.stdout:
            self._point_size = parse_screen_points(r.stdout)
        self.plane.run_sync(f"{self._idb} connect {self.udid} 2>/dev/null || true", timeout=30)
        self._start_log_capture()
        return True

    # --- perception / action ---
    def screenshot(self) -> bytes:
        # simctl returns ONLY the device framebuffer — no desktop chrome, no crop.
        return self.plane.screenshot()

    def screen_size(self) -> tuple[int, int]:
        # POINTS, not the screenshot's pixels — so center_px maps ratios to idb taps.
        return self._point_size

    def input(self, action: InputAction) -> None:
        if not self.udid:
            return
        t = action.type
        idb = self._idb
        if t == ActionType.CLICK:
            self.plane.run_sync(idb_tap_cmd(idb, self.udid, action.x, action.y))
        elif t == ActionType.DOUBLE_CLICK:
            self.plane.run_sync(idb_tap_cmd(idb, self.udid, action.x, action.y))
            self.plane.run_sync(idb_tap_cmd(idb, self.udid, action.x, action.y))
        elif t == ActionType.TYPE:
            if action.x is not None and action.y is not None:
                self.plane.run_sync(idb_tap_cmd(idb, self.udid, action.x, action.y))  # focus first
            self.plane.run_sync(idb_text_cmd(idb, self.udid, action.text or ""))
        elif t == ActionType.KEY:
            code = _HID_KEYS.get((action.key or "").lower())
            if code is not None:
                self.plane.run_sync(idb_key_cmd(idb, self.udid, code))
        elif t == ActionType.SCROLL:
            w, h = self._point_size
            cx, cy = w // 2, h // 2
            dy = h // 3 if action.direction == "down" else -h // 3
            self.plane.run_sync(idb_swipe_cmd(idb, self.udid, cx, cy, cx, cy - dy))
        elif t == ActionType.DRAG:
            self.plane.run_sync(idb_swipe_cmd(idb, self.udid, action.x, action.y, action.to_x, action.to_y))
        elif t == ActionType.WAIT:
            pass

    def detect_elements(self, screenshot: bytes) -> list[Element] | None:
        """a11y tree (idb describe-all) primary; OmniParser fallback-merge on opaque screens."""
        if not self.udid:
            return None
        r = self.plane.run_sync(f"{self._idb} ui describe-all --udid {self.udid} --json", timeout=30)
        if r is None or not (r.stdout or "").strip():
            return None  # idb unavailable → pure OmniParser path
        w, h = self._point_size
        a11y = parse_describe_all(r.stdout, w, h)
        if not a11y:
            return None  # nothing usable → OmniParser
        if len([e for e in a11y if e.interactivity]) >= _A11Y_MIN_INTERACTIVE:
            return _renumber(a11y)  # rich native tree
        vision = self._vision_detect(screenshot)  # opaque (webview/canvas) → merge
        return merge_elements(a11y, vision) if vision else _renumber(a11y)

    def rendered_elements(self) -> list[str]:
        """a11y labels of the interactive elements actually on screen (oracle source)."""
        if not self.udid:
            return []
        r = self.plane.run_sync(f"{self._idb} ui describe-all --udid {self.udid} --json", timeout=30)
        if r is None or not (r.stdout or "").strip():
            return []
        w, h = self._point_size
        return [e.label for e in parse_describe_all(r.stdout, w, h) if e.interactivity and e.label]

    def control_state(self, element_id: int) -> dict:
        """Live AXValue/AXLabel of the element at element_id — the read-back source for
        the input-integrity oracle (e.g. typed '007', field holds '7')."""
        if not self.udid:
            return {}
        r = self.plane.run_sync(f"{self._idb} ui describe-all --udid {self.udid} --json", timeout=30)
        if r is None or not (r.stdout or "").strip():
            return {}
        return describe_value_at(r.stdout, element_id)

    def logs(self) -> list[str]:
        r = self.plane.run_sync(f"cat {self.LOG_FILE} 2>/dev/null || true", timeout=15)
        text = r.stdout if r and r.stdout else ""
        lines = text.splitlines()
        if len(lines) < self._log_seen:  # rotated/truncated
            self._log_seen = 0
        new = lines[self._log_seen:]
        self._log_seen = len(lines)
        return new

    def teardown(self) -> None:
        if self.udid:
            self.plane.run_sync(f"xcrun simctl shutdown {self.udid} 2>/dev/null || true", timeout=30)
        self.plane.stop()

    # --- helpers ---
    def _ensure_device(self) -> None:
        if self.udid:
            self.plane.run_sync(f"xcrun simctl boot {self.udid} 2>/dev/null || true", timeout=120)
            return
        r = self.plane.run_sync("xcrun simctl list devices available -j", timeout=30)
        udid = first_iphone_udid(r.stdout if r and r.stdout else "")
        if not udid:
            self.plane.run_sync('xcrun simctl create Inspector "iPhone 15" 2>/dev/null || true', timeout=60)
            r = self.plane.run_sync("xcrun simctl list devices available -j", timeout=30)
            udid = first_iphone_udid(r.stdout if r and r.stdout else "")
        self.udid = udid
        if udid:
            self.plane.run_sync(f"xcrun simctl boot {udid} 2>/dev/null || true", timeout=120)

    def _apple_build_cmd(self, app_dir: str) -> str:
        """Regenerate the xcodegen project (if any), detect the scheme, and build.

        -derivedDataPath requires -scheme; -destination needs a real simulator
        (a runtime must be installed). Both learned from the fixture's run.sh.
        """
        self.plane.run_sync(
            f"cd {shlex.quote(app_dir)} && (test -f project.yml && xcodegen generate || true)",
            timeout=120,
        )
        r = self.plane.run_sync(
            f"cd {shlex.quote(app_dir)} && xcodebuild -list -json 2>/dev/null", timeout=60,
        )
        scheme = first_scheme(r.stdout if r and r.stdout else "")
        sflag = f"-scheme {shlex.quote(scheme)} " if scheme else ""
        return (
            f"xcodebuild {sflag}-sdk iphonesimulator -configuration Debug "
            f"-destination 'generic/platform=iOS Simulator' -derivedDataPath ./build "
            f"CODE_SIGNING_ALLOWED=NO build"
        )

    def _bundle_id_of(self, app_path: str) -> str | None:
        r = self.plane.run_sync(
            f"plutil -extract CFBundleIdentifier raw {shlex.quote(app_path)}/Info.plist 2>/dev/null",
            timeout=30,
        )
        bid = (r.stdout.strip() if r and r.stdout else "")
        return bid or None

    def _app_executable(self, app_path: str) -> str | None:
        """CFBundleExecutable — the actual process name `log stream` matches on."""
        r = self.plane.run_sync(
            f"plutil -extract CFBundleExecutable raw {shlex.quote(app_path)}/Info.plist 2>/dev/null",
            timeout=30,
        )
        name = (r.stdout.strip() if r and r.stdout else "")
        return name or None

    def _start_log_capture(self) -> None:
        # Scope the stream to the app's process — otherwise simctl streams the WHOLE
        # simulator (hundreds of fitcored/backboardd/locationd daemon errors swamp the
        # app's own NSLog/os_log signal). logs() drains the file; scan_logs filters errors.
        self.plane.run_sync(f": > {self.LOG_FILE} || true", timeout=15)
        self._log_seen = 0
        # Scope to the app's process AND drop com.apple.* framework subsystems (UIKit
        # UIEvent chatter etc.) — only the app's own os_log/NSLog lines remain.
        pred = ""
        if self._app_process:
            pred = ("--predicate 'process == \"%s\" AND NOT subsystem BEGINSWITH \"com.apple\"' "
                    % self._app_process)
        self.plane.run_bg(
            f"xcrun simctl spawn {self.udid} log stream --style compact --level error "
            f"{pred}> {self.LOG_FILE} 2>&1"
        )

    def _vision_detect(self, screenshot: bytes) -> list[Element]:
        try:
            if self._detector is None:
                from ..perception.detector import OmniParserDetector
                self._detector = OmniParserDetector(self.config)
            return self._detector.detect(screenshot)
        except Exception:
            return []


def _detect_ios_project(repo_path: str):
    """Detect the iOS build kit. Falls back to apple-native; never raises."""
    from ..launch.detect import detect_project

    try:
        return detect_project(repo_path)  # handles JS (RN/expo) + the native arm
    except Exception:
        from ..launch.detect import ProjectInfo
        return ProjectInfo(Surface.IOS, "apple-native", "none", "", None)
