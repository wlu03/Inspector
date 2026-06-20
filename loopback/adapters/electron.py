from __future__ import annotations

import json
import os
import shlex
import time

from ..launch.detect import detect_project
from ..models import Surface
from .desktop import DesktopAdapter


class ElectronAdapter(DesktopAdapter):
    """Electron apps in headless Linux (Xvfb/XFCE). See docs/11 Part H.

    Readiness is determined by waiting for the Electron window to appear (via
    xdotool), then forcing its geometry for stable, consistent screenshots.
    """

    surface = Surface.ELECTRON

    def __init__(self, config):
        super().__init__(config)
        self._name_hints: list[str] = []
        self._pre_windows: set[str] = set()
        self.window_id: str | None = None

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.project = detect_project(repo_path, Surface.ELECTRON)
        self._name_hints = self._read_name_hints(repo_path)
        self.sandbox.start()
        self.sandbox.upload_dir(repo_path)
        # snapshot existing windows so we can detect the new Electron one by diff
        self._pre_windows = self._enumerate_windows()
        cmd = dev_command or self.project.dev_command
        # container-required flags: --no-sandbox is mandatory; --disable-gpu avoids
        # "GPU process isn't usable. Goodbye." in headless.
        self.sandbox.run_dev(
            f"ELECTRON_DISABLE_SECURITY_WARNINGS=1 {cmd} -- "
            "--no-sandbox --disable-gpu --disable-dev-shm-usage "
            "--remote-debugging-port=9223"
        )

    def is_ready(self, timeout_s: float = 60.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            wid = self._find_window()
            if wid:
                self._fit_window(wid)
                self.window_id = wid
                time.sleep(1.0)  # let it paint before the first screenshot
                return True
            time.sleep(0.5)
        return False

    # --- window helpers (xdotool; E2B XFCE is X11) ---
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
