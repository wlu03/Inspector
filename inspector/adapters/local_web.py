"""Local web driver: headless Chrome via CDP — for REAL apps that don't fit the E2B
build-and-serve path (Angular/Capacitor/etc).

Three ways to get a URL, in priority order:
  1. INSPECTOR_WEB_URL   — attach to an already-running dev server (e.g. ng serve :4200)
  2. INSPECTOR_WEB_DIST  — serve a prebuilt static dir (e.g. dist/browser) ourselves
  3. the project's dev command (best-effort) — run it and wait for its port

Then launch headless Chrome with --remote-debugging-port and drive it over CDP, reusing
all of LocalElectronAdapter's CDP perception/action (screenshot, DOM grounding, input,
console). No window, no VM, works for any framework.
"""
from __future__ import annotations

import functools
import http.server
import os
import shlex
import socketserver
import subprocess
import threading
import time
import urllib.request

from ..models import Surface
from .local_electron import LocalElectronAdapter

_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/opt/homebrew/bin/chromium",
)


def chrome_bin() -> str:
    for p in _CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return "google-chrome"


class LocalWebAdapter(LocalElectronAdapter):
    """Drive a web app in headless Chrome over CDP. Inherits all the CDP
    screenshot/input/DOM-grounding/console methods from the Electron adapter; only the
    launch (Chrome at a URL, not `electron .`) and teardown (also stop our static
    server) differ."""

    surface = Surface.WEB

    def __init__(self, config):
        super().__init__(config)
        self._httpd: socketserver.TCPServer | None = None
        self._url: str | None = None

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.repo_path = repo_path
        url = os.environ.get("INSPECTOR_WEB_URL")
        if not url:
            dist = os.environ.get("INSPECTOR_WEB_DIST")
            url = self._serve_static(dist) if dist else self._run_dev_server(repo_path, dev_command)
        self._url = url

        udir = f"/tmp/inspector-chrome-{self._cdp_port}"
        flags = ("--headless=new --no-first-run --no-default-browser-check --disable-gpu "
                 "--disable-backgrounding-occluded-windows --disable-renderer-backgrounding "
                 "--window-size=1280,900")
        cmd = (f'{shlex.quote(chrome_bin())} --remote-debugging-port={self._cdp_port} '
               f'--remote-allow-origins=* --user-data-dir={udir} {flags} {shlex.quote(url)}')
        self._proc = subprocess.Popen(
            shlex.split(cmd), start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _hide_window(self) -> None:
        return  # headless Chrome has no window — nothing to hide

    def _serve_static(self, dist: str) -> str:
        """Serve a prebuilt static dir (SPA) on a free localhost port."""
        directory = os.path.abspath(dist)
        handler = functools.partial(_SPAHandler, directory=directory)
        self._httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{port}/"

    def _run_dev_server(self, repo_path: str, dev_command: str | None) -> str:
        """Best-effort: run the project's dev command + wait for its port to answer."""
        from ..launch.detect import detect_project
        proj = detect_project(repo_path, Surface.WEB)
        cmd = dev_command or proj.dev_command
        port = proj.default_port or 4200
        if not os.path.isdir(os.path.join(repo_path, "node_modules")):
            subprocess.run(["npm", "install"], cwd=repo_path, capture_output=True, timeout=1200)
        self._proc2 = subprocess.Popen(
            shlex.split(cmd), cwd=repo_path, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PORT": str(port), "BROWSER": "none"},
        )
        url = f"http://localhost:{port}/"
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                urllib.request.urlopen(url, timeout=2)
                return url
            except Exception:
                time.sleep(1.0)
        return url

    def teardown(self) -> None:
        super().teardown()
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None
        proc2 = getattr(self, "_proc2", None)
        if proc2 is not None:
            try:
                os.killpg(os.getpgid(proc2.pid), 15)
            except Exception:
                pass


class _SPAHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server that falls back to index.html for client-side routes (SPA)."""

    def do_GET(self):  # noqa: N802
        path = self.translate_path(self.path)
        if not os.path.exists(path) and "." not in os.path.basename(self.path):
            self.path = "/index.html"  # SPA deep link → serve the app shell
        return super().do_GET()

    def log_message(self, *args):  # silence
        pass
