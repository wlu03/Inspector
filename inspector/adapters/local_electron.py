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
import urllib.parse
import urllib.request

from ..config import Config
from ..launch.detect import detect_project
from ..models import ActionType, Element, Surface
from .base import InputAction, SurfaceAdapter
from .cdp_client import (
    DOM_ELEMENTS_JS,
    DOM_TEXT_JS,
    CDPClient,
    origin_of,
    parse_dom_elements,
    parse_text_elements,
)

CDP_PORT = 9223
# Page.navigate REPLACES the document, and on a packaged Electron app the document IS
# the app shell: a file:// bundle whose renderer was handed its IPC bridge by a preload
# script. Sending it to an in-app route string blanks the window instead of routing
# ('/does-not-exist' resolves to file:///does-not-exist), and the router that could have
# routed back died with the document. So navigation is allowed only where it cannot do
# that — a same-document '#' route, or a shell served over http(s), where re-loading the
# origin simply boots the app again. Set this to 1 to waive the guard deliberately.
NAV_OPT_IN_ENV = "INSPECTOR_ALLOW_ELECTRON_NAVIGATE"
# One `InputAction.amount` unit is one wheel notch, and a notch is a ninth of the
# viewport — so the default amount of 3 still scrolls the third of a screen this adapter
# has always scrolled, while `amount` now actually changes the distance instead of being
# discarded (which made "scroll to the bottom of a long page" impossible in one call).
SCROLL_NOTCHES_PER_VIEWPORT = 9
# Per-instance CDP ports so multiple Electron sessions can run in PARALLEL (the
# fan-out verifier) without colliding on a single debugging port.
_port_seq = itertools.count(CDP_PORT)


class LocalElectronAdapter(SurfaceAdapter):
    surface = Surface.ELECTRON
    # CDP dispatches real mouse events, so this surface can do the two the pixel-level
    # backends can't: a hover that updates `:hover`, and a right button that raises
    # `contextmenu`. Inherited by LocalWebAdapter.
    input_actions = SurfaceAdapter.input_actions | {ActionType.HOVER, ActionType.RIGHT_CLICK}

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
        # the --disable-*backgrounding/throttling flags keep the renderer PAINTING even
        # when the window is hidden (headless) — else captureScreenshot returns empty.
        full = (f"{cmd} -- --remote-debugging-port={self._cdp_port} "
                f"--remote-allow-origins=* --no-sandbox "
                f"--disable-backgrounding-occluded-windows --disable-renderer-backgrounding "
                f"--disable-background-timer-throttling")
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
                    self._hide_window()      # headless: no window on screen
                    time.sleep(0.5)          # let the renderer paint
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

    def _hide_window(self) -> None:
        """macOS has no headless Electron, but we can HIDE the app's windows (Cmd-H) so
        nothing shows on screen — CDP captureScreenshot still works (it grabs the renderer
        compositor, not the OS window). Set INSPECTOR_SHOW_ELECTRON=1 to watch instead."""
        if os.environ.get("INSPECTOR_SHOW_ELECTRON") == "1":
            return
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to set visible of '
                 '(every process whose name contains "Electron") to false'],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

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
        elif t == ActionType.RIGHT_CLICK:
            self.cdp.right_click(action.x, action.y)
        elif t == ActionType.HOVER:
            self.cdp.hover(action.x, action.y)
        elif t == ActionType.TYPE:
            if action.x is not None and action.y is not None:
                self.cdp.click(action.x, action.y)  # focus the field first
            self.cdp.type_text(action.text or "")
        elif t == ActionType.KEY:
            self.cdp.key(action.key or "")
        elif t == ActionType.SCROLL:
            w, h = self._viewport
            notch = max(1, h // SCROLL_NOTCHES_PER_VIEWPORT) * max(1, action.amount)
            dy = notch if action.direction != "up" else -notch
            self.cdp.scroll(w // 2, h // 2, dy)
        elif t == ActionType.DRAG:
            self.cdp.drag(action.x, action.y, action.to_x, action.to_y)
        elif t == ActionType.WAIT:
            pass

    def navigate(self, url: str) -> bool:
        """Drive the renderer to `url` (absolute, or relative to the current document).

        Refuses rather than no-ops when the target would replace a file:// app shell —
        see NAV_OPT_IN_ENV. Inherited by LocalWebAdapter, where the app is always served
        over http(s) and the guard therefore never fires.
        """
        if not self.cdp or not url:
            return False
        target = self._nav_target(url)
        if target is None:
            return False
        return self.cdp.navigate(target)

    def _nav_target(self, url: str) -> str | None:
        """Resolve `url` against the document on screen; None if we must not go there."""
        current = self.cdp.current_url()
        if url.startswith("#"):
            return (current.split("#", 1)[0] + url) if current else None
        target = urllib.parse.urljoin(current, url) if current else url
        log = logging.getLogger("inspector")
        if not urllib.parse.urlsplit(target).scheme:
            log.warning("navigate(%r): no current URL to resolve a relative path against", url)
            return None
        if os.environ.get(NAV_OPT_IN_ENV) == "1":
            return target
        if current.startswith("file:"):
            log.warning(
                "navigate(%r) refused: the app shell is a file:// document, so navigating "
                "would replace the app itself rather than route inside it — use a '#' route, "
                "or set %s=1 if that is really what you want", url, NAV_OPT_IN_ENV)
            return None
        return target

    def go_back(self) -> bool:
        return self.cdp.back() if self.cdp else False

    def go_forward(self) -> bool:
        return self.cdp.forward() if self.cdp else False

    def reload(self) -> bool:
        return self.cdp.reload() if self.cdp else False

    def set_viewport(self, width: int, height: int, mobile: bool = False) -> bool:
        """Resize the emulated viewport, and move the click coordinate space with it.

        Updating `self._viewport` is not bookkeeping, it is the entire point: it is what
        `screen_size()` reports, what `screenshot()` downscales the capture to, and what
        the session multiplies element bbox ratios by to get a click. Emulating a 375px
        phone while this still said 1280 would leave every subsequent click computed at
        the old scale, i.e. off the right-hand edge of the screen the agent is looking
        at — a silent mis-click, which is far worse than a refused resize. It is set only
        after the browser confirms the override, so a failed resize leaves the old,
        still-accurate value in place.
        """
        if not self.cdp:
            return False
        w, h = int(width or 0), int(height or 0)
        if w <= 0 or h <= 0:
            return False
        if not self.cdp.set_viewport(w, h, mobile=mobile):
            return False
        self._viewport = (w, h)
        return True

    def clear_viewport(self) -> bool:
        """Drop the emulation override and re-read the real size back into `_viewport`,
        so the coordinate space follows the window back exactly as it followed it out."""
        if not self.cdp:
            return False
        ok = self.cdp.clear_viewport_override()
        self._refresh_viewport()
        return ok

    def capture_state(self) -> dict:
        """Snapshot the live session as {origin, cookies, local_storage, session_storage}.

        Deliberately a dumb flat dict of JSON values: its whole worth is that it outlives
        the process, so the agent (or the user) logs in ONCE, writes this to a file, and
        every later run replays it instead of driving the login form again.

        `origin` is read off the live page rather than taken on trust, because it is the
        address `seed_state` navigates to when replaying — storage recorded under the
        wrong origin is invisible to the app and fails without a sound.
        """
        if not self.cdp:
            return {}
        origin = origin_of(self.cdp.current_url())
        storage = self.cdp.get_storage(origin)
        return {
            "origin": origin,
            "cookies": self.cdp.get_cookies(),
            "local_storage": storage.get("local", {}),
            "session_storage": storage.get("session", {}),
        }

    def seed_state(self, state: dict) -> bool:
        """Replay a captured session, in the one order that actually works.

        cookies → navigate(origin) → local/sessionStorage → reload, and every step of that
        sequence is load-bearing:

        * Cookies go FIRST because they are keyed by domain rather than by the document on
          screen, so setting them before the app loads means its first request is already
          authenticated and no login redirect ever happens.
        * Storage cannot go first. Both stores are partitioned by origin and the only
          handle on an origin's store is a document loaded from it, so a write issued on
          about:blank lands in a store the app will never read — and raises nothing.
        * The reload is not cosmetic. The navigation above booted the app WITHOUT the
          storage, so it read an empty store and rendered logged out; only the second load
          sees the seeded state. Reading a token in a module-level initialiser is the norm
          in the apps this tool is pointed at, not an edge case.

        The ordering lives in here rather than in the caller precisely because getting it
        wrong fails silently — no error, no exception, just an app that is still logged
        out, which a caller cannot tell apart from a state file that had simply gone
        stale. True means the app is now running with this session installed, so the
        reload is part of the verdict; a False leaves the caller free to fall back to
        driving the login UI. Inherited unchanged by LocalWebAdapter.
        """
        if not self.cdp or not isinstance(state, dict):
            return False
        cookies = state.get("cookies") or []
        local = state.get("local_storage") or {}
        session = state.get("session_storage") or {}
        origin = str(state.get("origin") or "")
        if not cookies and not local and not session:
            return False  # nothing to install; saying True would be a lie
        ok = self.cdp.set_cookies(cookies) if cookies else True
        if origin and origin_of(origin) != origin_of(self.cdp.current_url()):
            if not self.navigate(origin):
                return False  # never seed storage into the origin we happen to be on
        if local or session:
            ok = self.cdp.set_storage(origin, local=local, session=session) and ok
        return self.reload() and ok

    def logs(self) -> list[str]:
        return self.cdp.drain_console() if self.cdp else []

    def network(self) -> list[dict]:
        """Requests the renderer made since the last call, straight off the CDP Network
        domain. Distinct from `logs()` — that stays a pure console tap, so a failed fetch
        is reported once, on the channel that actually knows its status and timing.
        Inherited unchanged by LocalWebAdapter."""
        return self.cdp.drain_network() if self.cdp else []

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

    def audit_dom(self) -> dict:
        """Deterministic DOM audit straight over the live CDP session.

        The local counterpart of the sandboxed `cdp.audit_dom` — same in-page
        expression, no Node runner in between. Inherited by LocalWebAdapter, so the
        default no-API-key configuration gets the hard-evidence tier too; without this
        override the base class's empty `{}` made every local audit read as a pass.
        """
        return self.cdp.audit_dom() if self.cdp else {}

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
