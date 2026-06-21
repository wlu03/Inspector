from __future__ import annotations

import dataclasses
import io
import json
import os
import shlex
import time

from ..launch.detect import detect_project
from ..models import Surface
from .desktop import DesktopAdapter
from .web import (
    APP_DIR,
    CDP_LISTENER_JS,
    CONSOLE_LOG,
    NODE_DIR,
    NODE_VERSION,
    cdp_page_ready,
)

# Electron's renderer exposes the Chrome DevTools Protocol on this port (set at launch).
ELECTRON_CDP_PORT = 9223
# Reuse the web console listener, just pointed at the Electron renderer's port.
_ELECTRON_LISTENER_JS = CDP_LISTENER_JS.replace("9222", str(ELECTRON_CDP_PORT))

# Native libs Electron needs that the stock XFCE/Firefox desktop may lack (best-effort).
_ELECTRON_DEPS = (
    "libgbm1 libxshmfence1 libdrm2 libnss3 libatk-bridge2.0-0 "
    "libgtk-3-0 libasound2 libxss1 libxtst6"
)


class ElectronAdapter(DesktopAdapter):
    """Electron apps in headless Linux (Xvfb/XFCE). See docs/11 Part H.

    Installs Node + deps, launches the app with Chromium's remote-debugging port,
    gates readiness on the renderer being inspectable (CDP), captures the renderer
    console (where bugs surface), and crops screenshots to the Electron window.
    """

    surface = Surface.ELECTRON

    def __init__(self, config):
        super().__init__(config)
        self._name_hints: list[str] = []
        self._pre_windows: set[str] = set()
        self.window_id: str | None = None
        self._console_started = False
        self._console_seen = 0
        self._last_crop: tuple[int, int, int, int] | None = None

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.project = detect_project(repo_path, Surface.ELECTRON)
        self._name_hints = self._read_name_hints(repo_path)
        self.sandbox.start()
        self.sandbox.upload_dir(repo_path)
        self._ensure_node()
        self._ensure_electron_deps()
        self.sandbox.run_sync(
            f"export PATH={NODE_DIR}/bin:$PATH && cd {APP_DIR} && npm install",
            timeout=600,
        )
        # snapshot existing windows so we can detect the new Electron one by diff
        self._pre_windows = self._enumerate_windows()
        cmd = dev_command or self.project.dev_command
        # container-required flags: --no-sandbox is mandatory; --disable-gpu avoids
        # "GPU process isn't usable. Goodbye." in headless. DISPLAY=:0 targets XFCE.
        self.sandbox.run_dev(
            f"export PATH={NODE_DIR}/bin:$PATH && cd {APP_DIR} && "
            f"DISPLAY=:0 ELECTRON_DISABLE_SECURITY_WARNINGS=1 {cmd} -- "
            "--no-sandbox --disable-gpu --disable-dev-shm-usage "
            f"--remote-debugging-port={ELECTRON_CDP_PORT}"
        )

    def is_ready(self, timeout_s: float = 120.0) -> bool:
        deadline = time.time() + timeout_s
        wid = None
        while time.time() < deadline:
            wid = self._find_window()
            if wid:
                break
            time.sleep(0.5)
        if not wid:
            return False
        self.window_id = wid
        self._fit_window(wid)
        self._kill_panel()  # keep the OS dock out of the cropped frame
        # gate readiness on the renderer being inspectable — console capture (where
        # the bugs surface) and the DOM-label oracle both depend on it.
        if not self._wait_cdp(timeout_s=30):
            return False
        self._start_console_capture()  # renderer console.* / exceptions → findings
        time.sleep(1.0)  # let it paint before the first screenshot
        return True

    # --- perception overrides (crop to the Electron window) ---
    def screenshot(self) -> bytes:
        png = self.sandbox.screenshot()
        geo = self._window_geometry()
        if geo is None and self._last_crop is not None:
            geo = self._last_crop  # keep last-known-good crop when geometry flakes
        if geo is None:
            return png
        x, y, w, h = geo
        from PIL import Image  # lazy

        im = Image.open(io.BytesIO(png)).convert("RGB")
        box = (max(x, 0), max(y, 0), min(x + w, im.width), min(y + h, im.height))
        if box[2] <= box[0] or box[3] <= box[1]:
            return png
        self._last_crop = (box[0], box[1], box[2] - box[0], box[3] - box[1])
        out = io.BytesIO()
        im.crop(box).save(out, format="PNG")
        return out.getvalue()

    def screen_size(self) -> tuple[int, int]:
        if self._last_crop:
            return self._last_crop[2], self._last_crop[3]
        return self.sandbox.screen_size()

    def input(self, action) -> None:
        # translate crop-relative coords back to absolute desktop coords
        if self._last_crop:
            x0, y0, _, _ = self._last_crop
            action = dataclasses.replace(
                action,
                x=None if action.x is None else action.x + x0,
                y=None if action.y is None else action.y + y0,
                to_x=None if action.to_x is None else action.to_x + x0,
                to_y=None if action.to_y is None else action.to_y + y0,
            )
        super().input(action)

    def logs(self) -> list[str]:
        """Dev-server stdout/stderr plus new renderer-console lines (CDP)."""
        return self.sandbox.drain_logs() + self._read_console()

    def rendered_elements(self) -> list[str]:
        """Visible interactive elements in the live DOM. Electron is Chromium, so it
        reuses the exact web/CDP workflow — only the debugging port differs (9223)."""
        from .cdp import dom_labels

        return dom_labels(self.sandbox, ELECTRON_CDP_PORT)

    # --- setup helpers ---
    def _ensure_node(self) -> None:
        url = f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-linux-x64.tar.xz"
        self.sandbox.run_sync(
            f"test -x {NODE_DIR}/bin/node || "
            f"(cd /home/user && curl -fsSL {url} -o node.tar.xz && "
            f"tar -xJf node.tar.xz && mv node-{NODE_VERSION}-linux-x64 {NODE_DIR})",
            timeout=300,
        )

    def _ensure_electron_deps(self) -> None:
        self.sandbox.run_sync(
            f"sudo apt-get install -y {_ELECTRON_DEPS} 2>/dev/null || "
            f"(sudo apt-get update -y && sudo apt-get install -y {_ELECTRON_DEPS}) || true",
            timeout=300,
        )

    # --- CDP readiness + console capture (renderer on 9223) ---
    def _wait_cdp(self, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            res = self.sandbox.run_sync(
                f"curl -fsS http://localhost:{ELECTRON_CDP_PORT}/json || true"
            )
            text = res.stdout if res and getattr(res, "stdout", "") else ""
            if cdp_page_ready(text):
                return True
            time.sleep(1.0)
        return False

    def _start_console_capture(self) -> None:
        if self._console_started:
            return
        try:
            self.sandbox.run_sync(f": > {CONSOLE_LOG} || true")  # clear any stale log
            self._console_seen = 0
            self.sandbox.write_file("/home/user/electron_cdp_listener.cjs", _ELECTRON_LISTENER_JS)
            self.sandbox.run_bg(
                f"export PATH={NODE_DIR}/bin:$PATH && node /home/user/electron_cdp_listener.cjs"
            )
            self._console_started = True
        except Exception:
            pass

    def _read_console(self) -> list[str]:
        res = self.sandbox.run_sync(f"cat {CONSOLE_LOG} 2>/dev/null || true")
        text = res.stdout if res and getattr(res, "stdout", "") else ""
        lines = text.splitlines()
        if len(lines) < self._console_seen:  # file truncated/rotated
            self._console_seen = 0
        new = lines[self._console_seen:]
        self._console_seen = len(lines)
        return new

    # --- window helpers (xdotool; E2B XFCE is X11) ---
    def _kill_panel(self) -> None:
        self.sandbox.run_sync(
            "xfce4-panel --quit 2>/dev/null; pkill -f xfce4-panel 2>/dev/null; true"
        )

    def _window_geometry(self) -> tuple[int, int, int, int] | None:
        if not self.window_id:
            return None
        res = self.sandbox.run_sync(
            f"xdotool getwindowgeometry --shell {self.window_id} 2>/dev/null || true"
        )
        if not (res and getattr(res, "stdout", "")):
            return None
        vals: dict[str, str] = {}
        for line in res.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
        try:
            return int(vals["X"]), int(vals["Y"]), int(vals["WIDTH"]), int(vals["HEIGHT"])
        except (KeyError, ValueError):
            return None

    def _enumerate_windows(self) -> set[str]:
        res = self.sandbox.run_sync("xdotool search --onlyvisible --name '.+' || true")
        if res and getattr(res, "stdout", ""):
            return set(res.stdout.split())
        return set()

    def _find_window(self) -> str | None:
        # 1) match by the app's name / WM_CLASS hints
        for hint in self._name_hints:
            for flag in ("--name", "--class"):
                res = self.sandbox.run_sync(
                    f"xdotool search --onlyvisible {flag} {shlex.quote(hint)} || true"
                )
                ids = res.stdout.split() if res and getattr(res, "stdout", "") else []
                if ids:
                    return ids[-1]
        # 2) fall back to any window that appeared since launch
        new = self._enumerate_windows() - self._pre_windows
        if new:
            return sorted(new)[-1]
        return None

    def _fit_window(self, wid: str) -> None:
        self.sandbox.run_sync(f"xdotool windowactivate {wid}")
        self.sandbox.run_sync(f"xdotool windowmove {wid} 0 0")
        self.sandbox.run_sync(f"xdotool windowsize {wid} 1280 800")

    @staticmethod
    def _read_name_hints(repo_path: str) -> list[str]:
        """Window-title / WM_CLASS candidates from package.json, plus dev fallbacks."""
        hints: list[str] = []
        try:
            with open(os.path.join(repo_path, "package.json")) as f:
                pkg = json.load(f)
            for key in ("productName", "name"):
                if pkg.get(key):
                    hints.append(str(pkg[key]))
            build = pkg.get("build")
            if isinstance(build, dict) and build.get("productName"):
                hints.append(str(build["productName"]))
        except Exception:
            pass
        hints += ["electron", "Electron"]  # dev-mode default class/name
        seen: set[str] = set()
        out: list[str] = []
        for h in hints:
            if h and h not in seen:
                seen.add(h)
                out.append(h)
        return out
