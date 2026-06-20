from __future__ import annotations

import re
import time

sleep = time.sleep  # re-exported so adapters don't import time directly

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_URL = re.compile(r"(https?://[^\s]+)")

_READY_PATTERNS = [
    re.compile(r"ready in \d+", re.I),
    re.compile(r"compiled successfully", re.I),
    re.compile(r"local:\s*https?://", re.I),
    re.compile(r"waiting on", re.I),
]
_CRASH_PATTERNS = [
    re.compile(r"EADDRINUSE", re.I),
    re.compile(r"command not found", re.I),
    re.compile(r"\b(error|cannot find module|module not found)\b", re.I),
]


def scan_ready_line(line: str) -> tuple[bool, str | None, bool]:
    """Return (is_ready_signal, url_if_any, is_crash) for a single log line."""
    clean = _ANSI.sub("", line)
    ready = any(p.search(clean) for p in _READY_PATTERNS)
    crash = any(p.search(clean) for p in _CRASH_PATTERNS)
    m = _URL.search(clean)
    return ready, (m.group(1) if m else None), crash


def http_ready(url: str, timeout_s: float = 2.0) -> bool:
    import httpx  # lazy

    try:
        r = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        return 200 <= r.status_code < 400
    except Exception:
        return False


def wait_until_ready(url: str, total_timeout_s: float = 90, interval_s: float = 0.5) -> bool:
    """The authoritative readiness gate: poll the dev URL for a 2xx/3xx."""
    deadline = time.time() + total_timeout_s
    while time.time() < deadline:
        if http_ready(url):
            return True
        time.sleep(interval_s)
    return False
