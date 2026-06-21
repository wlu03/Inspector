"""Serve the static dashboard on localhost so a finished test returns a clickable link.

The dashboard + replays are plain static files under the trace root, so a stdlib
http server pointed at that directory is all it takes — no extra deps, matching the
zero-build philosophy. The server runs as a daemon thread inside the MCP process and
is reused across calls; it dies when the MCP process exits (it's a dev-loop server).
"""

from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# trace_root -> (httpd, base_url). One server per directory, reused across tool calls.
_SERVERS: dict[str, tuple[ThreadingHTTPServer, str]] = {}
_LOCK = threading.Lock()

# Optional callable -> dict of currently-running sessions, wired by the MCP server.
# Powers the dashboard's live feed (GET /live.json) so in-progress runs show up
# mid-run without rebuilding the static files.
_live_provider = None
# Optional callable (path:str, body:dict) -> dict for POST /api/* (e.g. Fix with Devin).
_action_handler = None


def set_live_provider(fn) -> None:
    """Register a `() -> dict` that returns live session state for GET /live.json."""
    global _live_provider
    _live_provider = fn


def set_action_handler(fn) -> None:
    """Register a `(path, body) -> dict` to handle dashboard POST /api/* actions."""
    global _action_handler
    _action_handler = fn


class _QuietHandler(SimpleHTTPRequestHandler):
    # The MCP talks over stdio — never write request logs to stdout.
    def log_message(self, *args) -> None:  # noqa: D401
        pass

    def _send_json(self, data: dict, code: int = 200) -> None:
        import json as _json

        body = _json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self) -> None:
        if self.path.split("?")[0].rstrip("/") == "/live.json":
            try:
                data = _live_provider() if _live_provider else {"sessions": []}
            except Exception:
                data = {"sessions": []}
            self._send_json(data)
            return
        super().do_GET()

    def do_POST(self) -> None:
        import json as _json

        path = self.path.split("?")[0]
        if not path.startswith("/api/"):
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = _json.loads(raw or b"{}")
        except Exception:
            body = {}
        if _action_handler is None:
            self._send_json({"error": "no action handler registered"}, 503)
            return
        try:
            self._send_json(_action_handler(path, body))
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)[:200]}, 500)


def ensure_server(trace_root: str, port: int = 7321, host: str = "127.0.0.1") -> str:
    """Start (once) a localhost static server for `trace_root`; return its base URL.

    Tries `port` first for a stable link, then an ephemeral port if it's taken.
    Bound to 127.0.0.1 — local only, never exposed off the machine.
    """
    with _LOCK:
        existing = _SERVERS.get(trace_root)
        if existing is not None:
            return existing[1]

        handler = functools.partial(_QuietHandler, directory=trace_root)
        httpd = None
        for candidate in (port, 0):  # stable port, else any free port
            try:
                httpd = ThreadingHTTPServer((host, candidate), handler)
                break
            except OSError:
                continue
        if httpd is None:  # pragma: no cover - both binds failed
            raise OSError("could not bind a dashboard port")

        actual = httpd.server_address[1]
        threading.Thread(
            target=httpd.serve_forever, name="inspector-dashboard", daemon=True
        ).start()
        url = f"http://{host}:{actual}"
        _SERVERS[trace_root] = (httpd, url)
        return url


def publish(trace_root: str, session_id: str | None = None, port: int = 7321) -> dict:
    """Rebuild the dashboard, ensure the localhost server is up, return the links.

    Returns `dashboard_url` (deep-linked to the run when `session_id` is given, so the
    row is highlighted) and `replay_url` (straight into that session's replay).
    """
    from .build import build_dashboard

    build_dashboard(trace_root)
    base = ensure_server(trace_root, port)
    out = {"dashboard_url": f"{base}/dashboard.html"}
    if session_id:
        out["dashboard_url"] = f"{base}/dashboard.html#{session_id}"
        out["replay_url"] = f"{base}/{session_id}/index.html"
    return out
