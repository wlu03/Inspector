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
        # 1) build the APK from source (gradle / expo prebuild), locally
        from ..android_build import AndroidBuilder  # M2.3 — not yet implemented

        build = AndroidBuilder(self.config).build(repo_path)
        self.package, self.activity = build.package, build.activity

        # 2) boot the local Android Emulator (no remote host / SSH / kernel modules)
        #    and get a LOCAL adb transport to it.
        self.plane = self._make_runtime()
        serial = self.plane.start()                 # emulator -avd … → "emulator-5554"
        self.adb = self.adb or self._make_transport(serial)
        self.adb.wait_for_device()

        # 3) keep the screen awake, install + launch; clear logcat first
        self._wake()
        self.adb.install(build.apk_path)
        self.adb.shell("logcat -c")
        self.adb.shell(f"am start -n {self.package}/{self.activity}")

    def is_ready(self, timeout_s: float = 60.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            out = self.adb.shell("dumpsys activity activities | grep -E 'mResumedActivity|ResumedActivity'")
            if self.package and self.package in out:
                self._wake()        # display ON before the first screencap
                time.sleep(1.0)     # let the first frame paint
                return True
            time.sleep(1.0)
        return False

    def _wake(self) -> None:
        """Keep the display on + unlocked so screencap never returns an empty (asleep)
        frame — the failure that made OmniParser reject the image. Idempotent."""
        self.adb.shell("svc power stayon true")
        self.adb.shell("input keyevent KEYCODE_WAKEUP")
        self.adb.shell("wm dismiss-keyguard")

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
        # guard against None coords interpolating the literal "None" into the shell cmd
        if t in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.DRAG):
            if action.x is None or action.y is None:
                return
        if t == ActionType.DRAG and (action.to_x is None or action.to_y is None):
            return
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
            if None not in (action.x, action.y, action.to_x, action.to_y):
                self.adb.shell(f"input swipe {action.x} {action.y} {action.to_x} {action.to_y} 300")
        elif t == ActionType.WAIT:
            time.sleep(1.0)

    # --- ears (the deterministic crash/error signal) ---
    def logs(self) -> list[str]:
        # Scope to the app's process so logcat doesn't return other apps' noise (the
        # background NullPointerExceptions we saw). If the app crashed (no pid), fall
        # back to filtering the raw buffer to our package + crash markers.
        pid = self.adb.shell(f"pidof -s {self.package}").strip() if self.package else ""
        raw = self.adb.logcat("crash,main", pid=pid or None)
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if not pid and self.package:
            lines = filter_app_logs(lines, self.package)
        return lines

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

    def _make_runtime(self):
        """Pick the Android runtime. Default = local emulator (this machine); set
        ANDROID_RUNTIME=redroid for the remote container plane."""
        from ..planes.android import LocalEmulatorRuntime, RedroidRuntime
        if getattr(self.config, "android_runtime", "local") == "redroid":
            return RedroidRuntime(self.config)
        return LocalEmulatorRuntime(self.config)

    def _make_transport(self, serial: str):
        from ..adb import AdbTransport
        # local emulator → local adb (no SSH); SSH is only for the remote redroid plane.
        if getattr(self.config, "android_runtime", "local") == "redroid":
            return AdbTransport(
                serial=serial,
                ssh_host=getattr(self.config, "android_ssh_host", None),
                ssh_user=getattr(self.config, "android_ssh_user", None),
                ssh_key=getattr(self.config, "android_ssh_key", None),
            )
        return AdbTransport(serial=serial)  # local mode


# --- pure helpers (unit-tested, no device) ---

def filter_app_logs(lines: list[str], package: str) -> list[str]:
    """Keep only the app's lines + crash markers when no pid is available (app crashed).
    Drops unrelated background-process noise. Pure."""
    out = []
    for ln in lines:
        if (package and package in ln) or "AndroidRuntime" in ln or "FATAL" in ln:
            out.append(ln)
    return out


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
