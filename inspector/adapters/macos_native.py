"""Native macOS (AppKit/SwiftUI) adapter — local only.

The Mac analog of the iOS adapter: the `macax` Swift helper (compiled on first use)
dumps the app's front-window accessibility tree as JSON and posts CGEvent taps/keys;
`screencapture` grabs the window. Grounding is the AX tree (detect_elements), so the
pure-computer-use action path is unchanged. Coordinates follow the same point/pixel
contract as iOS: screenshots are pixels, screen_size() returns window POINTS, taps go
through global screen points.

Requires Accessibility + Screen Recording permission for the controlling process.
"""

from __future__ import annotations

import glob
import json
import os
import shlex
import subprocess
import time

from ..config import Config
from ..models import ActionType, Element, Surface
from .base import InputAction, SurfaceAdapter
from .ios import first_scheme  # reuse the xcodebuild scheme detector

# AX roles that are actionable (the rest — windows/groups/static text — are context).
_INTERACTIVE = {
    "AXButton", "AXTextField", "AXTextArea", "AXCheckBox", "AXRadioButton",
    "AXPopUpButton", "AXMenuButton", "AXComboBox", "AXSlider", "AXLink",
    "AXMenuItem", "AXSegmentedControl", "AXIncrementor", "AXStepper", "AXDisclosureTriangle",
}
_CONTAINERS = {"AXWindow", "AXGroup", "AXSplitGroup", "AXScrollArea", "AXLayoutArea", "AXUnknown"}

# macOS virtual keycodes for the keys the loop emits.
_KEYCODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "left": 123, "right": 124, "down": 125, "up": 126,
}

_LOG_FILE = "/tmp/inspector_macos.log"


def ax_interactive(role: str) -> bool:
    return role in _INTERACTIVE


def parse_ax_dump(raw: str) -> tuple[dict, list[Element]]:
    """Parse `macax dump` JSON → (window bounds, Element[]). Pure.

    Element bbox is normalized to the WINDOW (0..1) so the marker/center math is
    resolution-independent. Drops empty containers; keeps interactive + labeled nodes.
    """
    try:
        d = json.loads(raw)
    except Exception:
        return {}, []
    win = d.get("window") or {}
    wx, wy, ww, wh = win.get("x", 0), win.get("y", 0), win.get("w", 0), win.get("h", 0)
    if not ww or not wh:
        return win, []
    out: list[Element] = []
    for e in d.get("elements", []):
        x, y, w, h = e.get("x", 0), e.get("y", 0), e.get("w", 0), e.get("h", 0)
        if w <= 0 or h <= 0:
            continue
        role = e.get("role", "")
        label = (e.get("label") or e.get("value") or "").strip()
        interactive = ax_interactive(role)
        if not interactive and (not label or role in _CONTAINERS):
            continue  # skip empty containers / chrome
        bbox = [
            min(1.0, max(0.0, (x - wx) / ww)), min(1.0, max(0.0, (y - wy) / wh)),
            min(1.0, max(0.0, (x + w - wx) / ww)), min(1.0, max(0.0, (y + h - wy) / wh)),
        ]
        out.append(Element(id=0, label=label[:80], role=role.replace("AX", "").lower(),
                           bbox=bbox, interactivity=interactive, source="ax"))
    for i, el in enumerate(out):
        el.id = i
    return win, out


class MacNativeAdapter(SurfaceAdapter):
    """Drive a native macOS app via the AX tree + CGEvent (local, no VM)."""

    surface = Surface.MACOS

    def __init__(self, config: Config):
        self.config = config
        self.app = config.macos_app or "Calculator"  # app name / bundle id to drive
        self.pid: int | None = None
        self._helper: str | None = None
        self._app_path: str | None = None  # built .app path (for open/activate)
        self._win: dict = {}          # latest window bounds (screen points)
        self._point_size = (1280, 800)
        self._log_seen = 0
        self._log_proc: subprocess.Popen | None = None

    # --- helper compilation ---
    def _ensure_helper(self) -> str:
        if self._helper and os.path.exists(self._helper):
            return self._helper
        cache = os.path.expanduser("~/.inspector/bin/macax")
        if not os.path.exists(cache):
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            src = os.path.join(os.path.dirname(__file__), "macax.swift")
            subprocess.run(
                ["swiftc", "-O", src, "-o", cache, "-framework", "Cocoa",
                 "-framework", "ApplicationServices"],
                check=True, timeout=180,
            )
        self._helper = cache
        return cache

    def _macax(self, *args: str, timeout: int = 20) -> str:
        try:
            r = subprocess.run([self._ensure_helper(), *args], capture_output=True,
                               text=True, timeout=timeout)
            return r.stdout
        except Exception:
            return ""

    def _resolve_pid(self) -> int | None:
        # macax resolves the app by NAME or BUNDLE ID and reports its pid — robust
        # whether or not the app is frontmost, and for built fixtures whose display
        # name != bundle id (NSWorkspace name matching from a bare CLI tool is not).
        try:
            return json.loads(self._macax("dump", self.app)).get("pid")
        except Exception:
            return None

    def _activate(self) -> None:
        # CGEvent button presses only register on the frontmost app.
        if self._app_path:
            subprocess.run(["open", self._app_path], capture_output=True, timeout=15)
        else:
            subprocess.run(["open", "-a", self.app], capture_output=True, timeout=15)

    @staticmethod
    def _is_mac_project(repo_path: str) -> bool:
        return (os.path.exists(os.path.join(repo_path, "project.yml"))
                or bool(glob.glob(os.path.join(repo_path, "*.xcodeproj"))))

    def _build_mac_app(self, repo_path: str) -> None:
        """xcodegen (if a spec) + xcodebuild for macOS → .app; resolve its bundle id."""
        if os.path.exists(os.path.join(repo_path, "project.yml")):
            subprocess.run(["xcodegen", "generate"], cwd=repo_path, capture_output=True, timeout=120)
        r = subprocess.run(["xcodebuild", "-list", "-json"], cwd=repo_path,
                           capture_output=True, text=True, timeout=60)
        scheme = first_scheme(r.stdout or "")
        cmd = ["xcodebuild"] + (["-scheme", scheme] if scheme else [])
        cmd += ["-configuration", "Debug", "-derivedDataPath", "build", "CODE_SIGNING_ALLOWED=NO", "build"]
        subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=600)
        apps = glob.glob(os.path.join(repo_path, "build/Build/Products/Debug/*.app"))
        if apps:
            self._app_path = apps[0]
            self.app = self._bundle_id_of(apps[0]) or self.app

    @staticmethod
    def _bundle_id_of(app_path: str) -> str | None:
        try:
            r = subprocess.run(
                ["plutil", "-extract", "CFBundleIdentifier", "raw",
                 os.path.join(app_path, "Contents", "Info.plist")],
                capture_output=True, text=True, timeout=15,
            )
            return r.stdout.strip() or None
        except Exception:
            return None

    # --- lifecycle ---
    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self._ensure_helper()
        if dev_command:
            subprocess.run(shlex.split(dev_command), capture_output=True, timeout=120)
        elif self._is_mac_project(repo_path):
            self._build_mac_app(repo_path)          # build → self._app_path + bundle id
            if self._app_path:
                subprocess.run(["open", self._app_path], capture_output=True, timeout=30)
        else:
            self._activate()                        # a pre-installed app by name
        for _ in range(40):
            self.pid = self._resolve_pid()
            if self.pid:
                break
            time.sleep(0.5)
        self._start_log_capture()

    def is_ready(self, timeout_s: float = 60.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not self.pid:
                self.pid = self._resolve_pid()
            if self.pid:
                win, _ = parse_ax_dump(self._macax("dump", str(self.pid)))
                if win.get("w"):
                    self._win = win
                    self._point_size = (int(win["w"]), int(win["h"]))
                    return True
            time.sleep(1.0)
        return False

    # --- perception / action ---
    def screenshot(self) -> bytes:
        win = self._win or {}
        if not win.get("w"):
            return b""
        x, y, w, h = int(win["x"]), int(win["y"]), int(win["w"]), int(win["h"])
        path = "/tmp/inspector_macos_shot.png"
        try:
            subprocess.run(["screencapture", "-x", "-o", f"-R{x},{y},{w},{h}", path],
                           capture_output=True, timeout=20)
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return b""

    def screen_size(self) -> tuple[int, int]:
        return self._point_size  # window POINTS

    def detect_elements(self, screenshot: bytes) -> list[Element] | None:
        if not self.pid:
            return None
        win, els = parse_ax_dump(self._macax("dump", str(self.pid)))
        if win.get("w"):
            self._win = win
            self._point_size = (int(win["w"]), int(win["h"]))
        return els or None

    def input(self, action: InputAction) -> None:
        win = self._win or {}
        wx, wy = win.get("x", 0), win.get("y", 0)
        self._activate()  # CGEvent button presses only register on the frontmost app
        t = action.type
        if t in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
            gx, gy = wx + (action.x or 0), wy + (action.y or 0)
            self._macax("tap", str(int(gx)), str(int(gy)))
            if t == ActionType.DOUBLE_CLICK:
                self._macax("tap", str(int(gx)), str(int(gy)))
        elif t == ActionType.TYPE:
            if action.x is not None and action.y is not None:
                self._macax("tap", str(int(wx + action.x)), str(int(wy + action.y)))
                time.sleep(0.1)
            self._macax("type", action.text or "")
        elif t == ActionType.KEY:
            code = _KEYCODES.get((action.key or "").lower())
            if code is not None:
                self._macax("key", str(code))

    def logs(self) -> list[str]:
        try:
            with open(_LOG_FILE) as f:
                lines = f.read().splitlines()
        except Exception:
            return []
        new = lines[self._log_seen:]
        self._log_seen = len(lines)
        return new

    def _start_log_capture(self) -> None:
        try:
            open(_LOG_FILE, "w").close()
            self._log_seen = 0
            pred = f'process == "{self.app}" AND NOT subsystem BEGINSWITH "com.apple"'
            self._log_proc = subprocess.Popen(
                ["log", "stream", "--style", "compact", "--level", "error", "--predicate", pred],
                stdout=open(_LOG_FILE, "w"), stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except Exception:
            self._log_proc = None

    def teardown(self) -> None:
        if self._log_proc is not None:
            try:
                self._log_proc.terminate()
            except Exception:
                pass
            self._log_proc = None
