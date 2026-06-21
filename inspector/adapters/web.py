from __future__ import annotations

import dataclasses
import io
import json
import shlex
import time

from ..launch.detect import detect_project
from ..models import Surface
from .desktop import DesktopAdapter

# Node 22 (has a built-in global WebSocket, used by the CDP console listener).
NODE_VERSION = "v22.11.0"
NODE_DIR = "/home/user/node"
APP_DIR = "/home/user/app"
CONSOLE_LOG = "/tmp/inspector_console.log"

_WINDOW_BLOCKLIST = {
    "xfce4-screensaver", "Xfwm4", "Desktop", "xfce4-panel",
    "wrapper-2.0", "Can't update Chrome", "",
}
# Substrings that mark a window as NOT our app (the stock template's Firefox, etc.).
# The old "any visible window" fallback would lock the screenshot crop onto these.
_WINDOW_BLOCK_SUBSTRINGS = ("firefox", "mozilla")

CDP_PORT = 9222

# Chromium-family binaries to drive (any supports the DevTools Protocol on :9222).
# The stock E2B desktop ships Firefox only — Firefox has no CDP, so we require one of
# these and install google-chrome if none is present.
_BROWSER_CANDIDATES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
)

# One-shot google-chrome install for the stock template (Ubuntu 22.04 + sudo).
_CHROME_INSTALL = (
    "curl -fsSL https://dl.google.com/linux/direct/"
    "google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb && "
    "sudo apt-get update -y && sudo apt-get install -y /tmp/chrome.deb"
)


def _is_app_window(name: str) -> bool:
    """Whether a window name is a plausible app window (not desktop/Firefox chrome). Pure."""
    if not name or name in _WINDOW_BLOCKLIST:
        return False
    low = name.lower()
    return not any(s in low for s in _WINDOW_BLOCK_SUBSTRINGS)


def pick_browser(present: set[str]) -> str | None:
    """First available Chromium-family binary, by preference order. Pure."""
    for cand in _BROWSER_CANDIDATES:
        if cand in present:
            return cand
    return None


def chrome_launch_cmd(
    binary: str, url: str, port: int = CDP_PORT, profile: str = "/tmp/inspector-profile"
) -> str:
    """Build the app-mode Chrome launch command (CDP enabled). Pure.

    `DISPLAY=:0` targets the desktop's X server (commands.run doesn't always inherit
    it) and `--disable-dev-shm-usage` keeps Chrome off the container's /dev/shm —
    without these two, Chrome never binds the CDP port and the session would fail.
    """
    return (
        f"DISPLAY=:0 {binary} --app={url} --no-sandbox --disable-gpu "
        "--disable-dev-shm-usage --window-position=0,0 --window-size=1280,800 "
        "--no-first-run --disable-session-crashed-bubble "
        f"--remote-debugging-port={port} --user-data-dir={profile}"
    )


def cdp_page_ready(json_text: str) -> bool:
    """True when CDP's /json lists an inspectable page target. Pure.

    This is the definitive "instrumented Chrome is actually up" signal — far more
    reliable than checking for a window, which false-positives on stray desktop
    windows (the readiness bug that dropped the agent onto a Firefox desktop).
    """
    try:
        targets = json.loads(json_text)
    except Exception:
        return False
    if not isinstance(targets, list):
        return False
    return any(
        isinstance(t, dict) and t.get("type") == "page" and t.get("webSocketDebuggerUrl")
        for t in targets
    )

# (a) In-sandbox CDP listener: connects to Chromium's remote-debugging port and
# appends console.* / uncaught exceptions / log entries to a file the adapter tails.
CDP_LISTENER_JS = r"""
const fs = require('fs');
const OUT = '/tmp/inspector_console.log';
const append = (s) => { try { fs.appendFileSync(OUT, s + '\n'); } catch (e) {} };
async function main() {
  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    try {
      const r = await fetch('http://localhost:9222/json');
      const ts = await r.json();
      page = ts.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (e) {}
    if (!page) await new Promise(r => setTimeout(r, 500));
  }
  if (!page) { append('[inspector] no CDP page target found'); return; }
  const attach = () => {
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    ws.addEventListener('open', () => {
      ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable' }));
      ws.send(JSON.stringify({ id: 2, method: 'Log.enable' }));
    });
    ws.addEventListener('message', (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.method === 'Runtime.consoleAPICalled') {
        const a = (m.params.args || []).map(x => (x.value ?? x.description ?? '')).join(' ');
        append('[console.' + m.params.type + '] ' + a);
      } else if (m.method === 'Runtime.exceptionThrown') {
        const d = m.params.exceptionDetails || {};
        append('[exception] ' + ((d.exception && d.exception.description) || d.text || ''));
      } else if (m.method === 'Log.entryAdded') {
        append('[log.' + m.params.entry.level + '] ' + m.params.entry.text);
      }
    });
    // reconnect if the debugger socket drops mid-session
    ws.addEventListener('close', () => setTimeout(attach, 1000));
    ws.addEventListener('error', () => { try { ws.close(); } catch (e) {} });
  };
  attach();
}
main();
"""


class WebAdapter(DesktopAdapter):
    """Web apps in an E2B desktop: install Node + deps, run the dev server, open
    Chromium in app mode, capture the browser console (CDP), and crop screenshots
    to the app window. See docs/11 Part G.
    """

    surface = Surface.WEB

    def __init__(self, config):
        super().__init__(config)
        self._port = 5173
        self._url: str | None = None
        self._window_id: str | None = None
        self._console_seen = 0
        self._console_started = False
        # (x0, y0, w, h) of the last screenshot crop, so clicks map back correctly.
        self._last_crop: tuple[int, int, int, int] | None = None

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.project = detect_project(repo_path, Surface.WEB)
        self._port = self.project.default_port or 5173
        self.sandbox.start()
        self.sandbox.upload_dir(repo_path)
        self._ensure_node()
        self.sandbox.run_sync(
            f"export PATH={NODE_DIR}/bin:$PATH && cd {APP_DIR} && npm install",
            timeout=420,
        )
        cmd = dev_command or self.project.dev_command
        args = self._host_port_args(self.project.framework, self._port)
        # PORT/HOST/BROWSER cover frameworks (CRA etc.) that don't take CLI flags.
        self.sandbox.run_dev(
            f"export PATH={NODE_DIR}/bin:$PATH && {cmd}{args}",
            envs={"PORT": str(self._port), "HOST": "0.0.0.0", "BROWSER": "none"},
        )

    def is_ready(self, timeout_s: float = 120.0) -> bool:
        self._url = f"http://localhost:{self._port}/"
        if not self._wait_http(self._url, timeout_s):
            return False

        # The stock template ships Firefox (no CDP). Resolve/install a Chromium-family
        # browser; without one we CANNOT instrument the app, so fail loudly rather than
        # false-positive on the desktop's Firefox window.
        binary = self._ensure_browser()
        if not binary:
            return False

        title = self._page_title()
        self.sandbox.run_bg(chrome_launch_cmd(binary, self._url))

        # Gate readiness on the CDP endpoint serving a page target — the definitive
        # "instrumented Chrome is up" signal. This is the core fix: previously readiness
        # rode on a window heuristic that matched any stray window.
        if not self._wait_cdp(timeout_s=45):
            return False

        # CDP is up → now locate the real Chrome app window for screenshot cropping.
        # With CDP confirmed and the title/Firefox filters, a match is the app window.
        deadline = time.time() + 30
        wid = None
        while time.time() < deadline:
            self.sandbox.run_sync(
                "for w in $(xdotool search --name \"Can.t update Chrome\" 2>/dev/null); "
                "do xdotool windowclose $w; done || true"
            )
            wid = self._find_app_window(title)
            if wid:
                break
            time.sleep(1.0)

        self._window_id = wid
        if not wid:
            return False  # the app window never appeared — the session isn't usable
        self.sandbox.run_sync(
            f"xdotool windowactivate {wid}; xdotool windowraise {wid}; "
            f"xdotool windowsize {wid} 1280 800; xdotool windowmove {wid} 0 0"
        )
        # Remove the XFCE panel/dock so the OS chrome is never inside the cropped frame.
        # The crop is the app-window rectangle; the always-on-top dock overlays it, so
        # cropping can't exclude it — without this an autonomous explorer clicks the
        # dock's browser icon and escapes the app onto the open desktop/internet.
        self.sandbox.run_sync(
            "xfce4-panel --quit 2>/dev/null; pkill -f xfce4-panel 2>/dev/null; true"
        )
        self._start_console_capture()  # (a)
        time.sleep(2.0)
        return True

    # --- perception / action overrides ---
    def screenshot(self) -> bytes:
        """(b) Crop the full-desktop screenshot to just the app window."""
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
        # Coordinates are computed against the cropped image, so report its size.
        if self._last_crop:
            return self._last_crop[2], self._last_crop[3]
        return self.sandbox.screen_size()

    def input(self, action) -> None:
        # Translate crop-relative coords back to absolute desktop coords.
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
        """Dev-server stdout/stderr plus new browser-console lines (a)."""
        return self.sandbox.drain_logs() + self._read_console()

    def rendered_elements(self) -> list[str]:
        """Visible interactive elements actually in the live DOM (via CDP). The
        per-surface hook for the code-aware missing-element oracle."""
        from .cdp import dom_labels
        return dom_labels(self.sandbox, CDP_PORT)

    def audit_dom(self) -> dict:
        """Deterministic DOM audit over CDP (axe-core, broken images, unlabeled inputs)."""
        from .cdp import audit_dom as _audit_dom
        return _audit_dom(self.sandbox, CDP_PORT)

    # --- helpers ---
    @staticmethod
    def _host_port_args(framework: str, port: int) -> str:
        if framework in ("vite", "sveltekit", "astro"):
            return f" -- --host 0.0.0.0 --port {port}"
        if framework == "next":
            return f" -- -H 0.0.0.0 -p {port}"
        return ""  # CRA and others rely on the PORT/HOST env vars passed to run_dev

    def _ensure_node(self) -> None:
        url = (
            f"https://nodejs.org/dist/{NODE_VERSION}/"
            f"node-{NODE_VERSION}-linux-x64.tar.xz"
        )
        self.sandbox.run_sync(
            f"test -x {NODE_DIR}/bin/node || "
            f"(cd /home/user && curl -fsSL {url} -o node.tar.xz && "
            f"tar -xJf node.tar.xz && mv node-{NODE_VERSION}-linux-x64 {NODE_DIR})",
            timeout=300,
        )

    def _wait_http(self, url: str, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            res = self.sandbox.run_sync(
                f"curl -fsS -o /dev/null -w '%{{http_code}}' {url} || true"
            )
            code = (res.stdout.strip() if res and getattr(res, "stdout", "") else "")
            if code[:1] in ("2", "3"):
                return True
            time.sleep(1.0)
        return False

    def _installed_browsers(self) -> set[str]:
        """Which Chromium-family binaries are on PATH (one sandbox round-trip).

        The trailing `; true` is load-bearing: if the LAST candidate isn't found the
        loop would exit non-zero, run_sync would return None, and we'd lose the stdout
        that already listed an installed browser (the bug that left binary=None even
        with google-chrome installed — verified live).
        """
        cands = " ".join(_BROWSER_CANDIDATES)
        res = self.sandbox.run_sync(
            f"for b in {cands}; do command -v $b >/dev/null 2>&1 && echo $b; done; true"
        )
        out = res.stdout if res and getattr(res, "stdout", "") else ""
        return {line.strip() for line in out.splitlines() if line.strip()}

    def _ensure_browser(self) -> str | None:
        """Resolve a CDP-capable browser, installing google-chrome if none exists.

        The stock E2B desktop template has only Firefox (no CDP). Returns the binary
        name to launch, or None if we couldn't get a Chromium-family browser — in
        which case the session must fail rather than run uninstrumented.
        """
        binary = pick_browser(self._installed_browsers())
        if binary:
            return binary
        self.sandbox.run_sync(_CHROME_INSTALL, timeout=300)  # one-time, ~30-60s
        return pick_browser(self._installed_browsers())

    def _wait_cdp(self, timeout_s: float) -> bool:
        """Block until CDP reports an inspectable page target (instrumented Chrome up)."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            res = self.sandbox.run_sync(
                f"curl -fsS http://localhost:{CDP_PORT}/json || true"
            )
            text = res.stdout if res and getattr(res, "stdout", "") else ""
            if cdp_page_ready(text):
                return True
            time.sleep(1.0)
        return False

    def _page_title(self) -> str | None:
        res = self.sandbox.run_sync(
            f"curl -fsS {self._url} | tr -d '\\n' | "
            "sed -n 's:.*<title>\\([^<]*\\)</title>.*:\\1:p'"
        )
        title = (res.stdout.strip() if res and getattr(res, "stdout", "") else "")
        return title or None

    def _find_app_window(self, title: str | None) -> str | None:
        if title:
            res = self.sandbox.run_sync(
                f"xdotool search --onlyvisible --name {shlex.quote(title)} || true"
            )
            ids = res.stdout.split() if res and getattr(res, "stdout", "") else []
            if ids:
                return ids[-1]
        res = self.sandbox.run_sync("xdotool search --onlyvisible --name '.+' || true")
        for wid in (res.stdout.split() if res and getattr(res, "stdout", "") else []):
            nm = self.sandbox.run_sync(f"xdotool getwindowname {wid} 2>/dev/null || true")
            name = nm.stdout.strip() if nm and getattr(nm, "stdout", "") else ""
            if _is_app_window(name):
                return wid
        return None

    def _window_geometry(self) -> tuple[int, int, int, int] | None:
        if not self._window_id:
            return None
        res = self.sandbox.run_sync(
            f"xdotool getwindowgeometry --shell {self._window_id} 2>/dev/null || true"
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

    def _start_console_capture(self) -> None:
        if self._console_started:
            return
        try:
            self.sandbox.run_sync(f": > {CONSOLE_LOG} || true")  # clear any stale log
            self._console_seen = 0
            self.sandbox.write_file("/home/user/cdp_listener.cjs", CDP_LISTENER_JS)
            self.sandbox.run_bg(
                f"export PATH={NODE_DIR}/bin:$PATH && node /home/user/cdp_listener.cjs"
            )
            self._console_started = True
        except Exception:
            pass

    def _read_console(self) -> list[str]:
        res = self.sandbox.run_sync(f"cat {CONSOLE_LOG} 2>/dev/null || true")
        text = res.stdout if res and getattr(res, "stdout", "") else ""
        lines = text.splitlines()
        if len(lines) < self._console_seen:  # file was truncated/rotated
            self._console_seen = 0
        new = lines[self._console_seen:]
        self._console_seen = len(lines)
        return new
