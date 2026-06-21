from __future__ import annotations

import re
import time
from xml.etree import ElementTree

from ..config import Config
from ..models import ActionType, Surface
from .base import InputAction, SurfaceAdapter

# Android keyevent codes for the keys the loop emits (input keyevent <code>).
_KEYCODES = {
    "Return": 66, "Enter": 66, "Tab": 61, "Escape": 111, "Back": 4,
    "Backspace": 67, "Home": 3, "Space": 62, "Delete": 67,
}

# uiautomator classes that are interactive even without clickable="true".
_INTERACTIVE_CLASSES = ("Button", "EditText", "CheckBox", "Switch", "ImageButton", "RadioButton")


class AndroidAdapter(SurfaceAdapter):
    """Drive an Android app on Redroid over adb (see infra/android-redroid/, docs/11 J).

    Same SurfaceAdapter contract as web/Electron — only the transport changes:
    screencap = eyes, `input` = hands, logcat = ears, uiautomator = the "DOM".
    The device-touching calls go through AdbTransport (mockable); the parsing/command
    helpers are pure and unit-tested with no device.
    """

    surface = Surface.ANDROID

    def __init__(self, config: Config, adb=None):
        self.config = config
        self.adb = adb           # AdbTransport; created in launch() if not injected
        self.plane = None        # RedroidRuntime
        self.package: str | None = None
        self.activity: str | None = None
        self._size: tuple[int, int] | None = None

    # --- lifecycle ---
    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        # 1) build the APK from source (gradle / expo prebuild) on the build host
        from ..android_build import AndroidBuilder  # M2.3 — not yet implemented
        from ..planes.android import RedroidRuntime  # M2.2

        build = AndroidBuilder(self.config).build(repo_path)
        self.package, self.activity = build.package, build.activity

        # 2) ensure a Redroid container is up and get an adb transport to it
        self.plane = RedroidRuntime(self.config)
        serial = self.plane.start()                 # docker up + adb connect → serial
        self.adb = self.adb or self._make_transport(serial)
        self.adb.wait_for_device()

        # 3) install + launch; clear logcat so logs() returns only post-launch lines
        self.adb.install(build.apk_path)
        self.adb.shell("logcat -c")
        self.adb.shell(f"am start -n {self.package}/{self.activity}")

    def is_ready(self, timeout_s: float = 60.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            out = self.adb.shell("dumpsys activity activities | grep -E 'mResumedActivity|ResumedActivity'")
            if self.package and self.package in out:
                time.sleep(1.0)  # let the first frame paint
                return True
            time.sleep(1.0)
        return False

    # --- eyes ---
    def screenshot(self) -> bytes:
        # PNG straight from SurfaceFlinger's framebuffer — no desktop, no crop
        return self.adb.exec_out("screencap -p")

    def screen_size(self) -> tuple[int, int]:
        if self._size is None:
            self._size = parse_wm_size(self.adb.shell("wm size")) or (1080, 1920)
        return self._size

    # --- hands ---
    def input(self, action: InputAction) -> None:
        t = action.type
        if t in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
            self.adb.shell(f"input tap {action.x} {action.y}")
            if t == ActionType.DOUBLE_CLICK:
                self.adb.shell(f"input tap {action.x} {action.y}")
        elif t == ActionType.TYPE:
            self.adb.shell(f"input text {escape_text(action.text or '')}")
        elif t == ActionType.KEY:
            code = keycode(action.key)
            if code is not None:
                self.adb.shell(f"input keyevent {code}")
        elif t == ActionType.SCROLL:
            cx, cy = self._center()
            dist = 600 if action.direction != "up" else -600
            self.adb.shell(f"input swipe {cx} {cy} {cx} {cy - dist} 300")
        elif t == ActionType.DRAG:
            self.adb.shell(f"input swipe {action.x} {action.y} {action.to_x} {action.to_y} 300")
        elif t == ActionType.WAIT:
            time.sleep(1.0)

    # --- ears (the deterministic crash/error signal) ---
    def logs(self) -> list[str]:
        raw = self.adb.logcat("crash,main")
        return [ln for ln in raw.splitlines() if ln.strip()]

    # --- the "DOM": view hierarchy for the missing-element oracle ---
    def rendered_elements(self) -> list[str]:
        xml = self.adb.shell("uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; cat /sdcard/ui.xml")
        return parse_uiautomator_labels(xml)

    def teardown(self) -> None:
        try:
            if self.adb and self.package:
                self.adb.shell(f"am force-stop {self.package}")
        finally:
            if self.plane:
                self.plane.stop()

    # --- helpers ---
    def _center(self) -> tuple[int, int]:
        w, h = self.screen_size()
        return w // 2, h // 2

    def _make_transport(self, serial: str):
        from ..adb import AdbTransport
        return AdbTransport(
            serial=serial,
            ssh_host=getattr(self.config, "android_ssh_host", None),
            ssh_user=getattr(self.config, "android_ssh_user", None),
            ssh_key=getattr(self.config, "android_ssh_key", None),
        )


# --- pure helpers (unit-tested, no device) ---

def keycode(key: str | None) -> int | None:
    if not key:
        return None
    if key in _KEYCODES:
        return _KEYCODES[key]
    return int(key) if str(key).isdigit() else None


def escape_text(text: str) -> str:
    """Quote text for `adb shell input text`: spaces become %s, then shell-quote."""
    import shlex
    return shlex.quote(text.replace(" ", "%s"))


def parse_wm_size(out: str) -> tuple[int, int] | None:
    """Parse `wm size` → (w, h). Prefers an Override size over Physical if present."""
    matches = re.findall(r"(\d+)x(\d+)", out or "")
    if not matches:
        return None
    w, h = matches[-1]  # Override line (if any) is printed last
    return int(w), int(h)


def parse_uiautomator_labels(xml: str) -> list[str]:
    """Interactive elements actually on screen, from the uiautomator hierarchy. Pure.

    The Android analog of the web DOM dump — the 'actually rendered' side of the
    code-aware missing-element oracle.
    """
    xml = _extract_hierarchy(xml)
    if not xml:
        return []
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for node in root.iter("node"):
        a = node.attrib
        interactive = a.get("clickable") == "true" or any(
            cls in a.get("class", "") for cls in _INTERACTIVE_CLASSES
        )
        if not interactive:
            continue
        label = (a.get("text") or a.get("content-desc") or "").strip()
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out


def _extract_hierarchy(xml: str) -> str | None:
    """Strip uiautomator's trailing 'dumped to:' chatter to the <hierarchy> span."""
    if not xml:
        return None
    start = xml.find("<hierarchy")
    end = xml.rfind("</hierarchy>")
    if start == -1 or end == -1:
        return None
    return xml[start : end + len("</hierarchy>")]
