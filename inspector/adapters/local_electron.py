"""Electron app running LOCALLY on the host, driven entirely via CDP — no VM, no
xdotool. Page.captureScreenshot for pixels, Input.* for clicks/typing, the renderer
console for findings, and the live DOM as the grounding source (exact element rects).
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import shlex
import signal
import subprocess
import time
import urllib.request

from ..config import Config
from ..launch.detect import detect_project
from ..models import ActionType, Element, Surface
from .base import InputAction, SurfaceAdapter
from .cdp_client import (
    DOM_ELEMENTS_JS,
    DOM_TEXT_JS,
    CDPClient,
    parse_dom_elements,
    parse_text_elements,
)

CDP_PORT = 9223
# Per-instance CDP ports so multiple Electron sessions can run in PARALLEL (the
# fan-out verifier) without colliding on a single debugging port.
_port_seq = itertools.count(CDP_PORT)


class LocalElectronAdapter(SurfaceAdapter):
    surface = Surface.ELECTRON

    def __init__(self, config: Config):
        self.config = config
        self.project = None
        self.repo_path: str | None = None
        self.cdp: CDPClient | None = None
        self._proc: subprocess.Popen | None = None
        self._cdp_port = next(_port_seq)   # unique per session → parallel-safe
        self._viewport: tuple[int, int] = (1280, 800)  # CSS px; refined at is_ready

    # --- lifecycle ---
    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.repo_path = repo_path
        self.project = detect_project(repo_path, Surface.ELECTRON)
        if not os.path.isdir(os.path.join(repo_path, "node_modules")):
            subprocess.run(["npm", "install"], cwd=repo_path, capture_output=True, timeout=900)
        cmd = dev_command or self.project.dev_command
        # --remote-allow-origins=* : modern Chromium rejects CDP WS connections from a
        # non-allowlisted Origin with a 403, which silently fails is_ready otherwise.
        full = (f"{cmd} -- --remote-debugging-port={self._cdp_port} "
                f"--remote-allow-origins=* --no-sandbox")
        # start_new_session so teardown can kill the whole electron process group
        self._proc = subprocess.Popen(
            shlex.split(full), cwd=repo_path, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def is_ready(self, timeout_s: float = 120.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            ws_url = self._page_ws_url()
            if ws_url:
                try:
                    self.cdp = CDPClient(ws_url)
                    self.cdp.enable()
                    self._refresh_viewport()
                    time.sleep(0.5)  # let the renderer paint
                    return True
                except Exception as exc:  # don't fail silently — surface why
                    logging.getLogger("inspector").warning("CDP connect failed: %s", exc)
                    return False
            time.sleep(1.0)
        return False

    def _page_ws_url(self) -> str | None:
        try:
            data = json.loads(
                urllib.request.urlopen(
                    f"http://localhost:{self._cdp_port}/json", timeout=2).read()
            )
            for t in data:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            return None
        return None

    def _refresh_viewport(self) -> None:
        v = self.cdp.evaluate("JSON.stringify([window.innerWidth, window.innerHeight])")
        try:
            w, h = json.loads(v)
            if w and h:
                self._viewport = (int(w), int(h))
        except Exception:
            pass

    # --- perception / action ---
    def screenshot(self) -> bytes:
        if not self.cdp:
            return b""
        raw = self.cdp.screenshot()
        # Page.captureScreenshot is at devicePixelRatio (2x on Retina); downscale to the
        # CSS viewport so screenshot px == screen_size() == Input.* coords — a
        # screenshot-pixel-derived click then lands correctly (Retina-safe). #7.
        try:
            import io

            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            if img.size != self._viewport:
                buf = io.BytesIO()
                img.resize(self._viewport, Image.LANCZOS).save(buf, format="PNG")
                return buf.getvalue()
        except Exception:
            pass
        return raw

    def screen_size(self) -> tuple[int, int]:
        return self._viewport  # CSS px — matches the Input.* coordinate space

    def input(self, action: InputAction) -> None:
        if not self.cdp:
            return
        t = action.type
        if t == ActionType.CLICK:
            self.cdp.click(action.x, action.y)
        elif t == ActionType.DOUBLE_CLICK:
            self.cdp.click(action.x, action.y, clicks=2)
        elif t == ActionType.TYPE:
            if action.x is not None and action.y is not None:
                self.cdp.click(action.x, action.y)  # focus the field first
            self.cdp.type_text(action.text or "")
        elif t == ActionType.KEY:
            self.cdp.key(action.key or "")
        elif t == ActionType.SCROLL:
            w, h = self._viewport
            dy = h // 3 if action.direction == "down" else -h // 3
            self.cdp.scroll(w // 2, h // 2, dy)
        elif t == ActionType.DRAG:
            self.cdp.drag(action.x, action.y, action.to_x, action.to_y)
        elif t == ActionType.WAIT:
            pass

    def logs(self) -> list[str]:
        return self.cdp.drain_console() if self.cdp else []

    def detect_elements(self, screenshot: bytes) -> list[Element] | None:
        """DOM is the grounding source — exact element rects, no OmniParser needed."""
        if not self.cdp:
            return None
        vw, vh = self._viewport
        raw = self.cdp.evaluate(DOM_ELEMENTS_JS)
        if not raw:
            return None
        els = parse_dom_elements(raw, vw, vh)
        return els or None

    def control_state(self, element_id: int) -> dict:
        return self.cdp.control_state(element_id) if self.cdp else {}

    def text_elements(self) -> list[Element]:
        if not self.cdp:
            return []
        vw, vh = self._viewport
        raw = self.cdp.evaluate(DOM_TEXT_JS)
        return parse_text_elements(raw, vw, vh) if raw else []

    def rendered_elements(self) -> list[str]:
        if not self.cdp:
            return []
        vw, vh = self._viewport
        raw = self.cdp.evaluate(DOM_ELEMENTS_JS)
        return [e.label for e in parse_dom_elements(raw or "[]", vw, vh) if e.label]

    def teardown(self) -> None:
        if self.cdp:
            self.cdp.close()
            self.cdp = None
        if self._proc is not None:
            try:
                pgid = os.getpgid(self._proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    self._proc.wait(timeout=5)  # reap; avoid a zombie + free CDP port 9223
                except Exception:
                    os.killpg(pgid, signal.SIGKILL)  # Electron ignored SIGTERM → force it
                    try:
                        self._proc.wait(timeout=5)
                    except Exception:
                        pass
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
