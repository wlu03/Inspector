from __future__ import annotations

import atexit
import json
import os

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from . import detection
from .config import Config
from .models import ActionType, Severity, Surface
from .session import SessionManager

CONFIG = Config.from_env()
MANAGER = SessionManager(CONFIG)
mcp = FastMCP("LoopBack")


@atexit.register
def _cleanup_all() -> None:
    """Best-effort teardown of every live sandbox on process exit."""
    for sid in list(MANAGER.sessions.keys()):
        try:
            MANAGER.stop(sid)
        except Exception:
            pass


def _result(image: Image, data: dict):
    """Return an image + structured data, using ToolResult when available."""
    try:
        from fastmcp.tools.tool import ToolResult

        return ToolResult(content=[image], structured_content=data)
    except Exception:  # pragma: no cover - fallback for older fastmcp
        return [image, data]


@mcp.tool
def launch_app(
    repo_path: str,
    surface: str | None = None,
    dev_command: str | None = None,
    goal: str = "",
) -> dict:
    """Boot the app in a sandbox and wait until it's interactive.

    Detects the framework/dev command, launches it on the right surface, and
    blocks until ready. Returns the session_id used by the other tools. On
    failure the sandbox is torn down so nothing is leaked.
    """
    surf = Surface(surface) if surface else None
    session = MANAGER.create(repo_path, surf, goal)
    try:
        ready = session.launch(dev_command)
    except Exception as exc:
        MANAGER.stop(session.record.id)  # kill the sandbox, drop the session
        return {
            "session_id": session.record.id,
            "surface": session.record.surface.value,
            "state": "error",
            "ready": False,
            "error": str(exc)[:300],
        }
    return {
        "session_id": session.record.id,
        "surface": session.record.surface.value,
        "state": session.record.state.value,
        "ready": ready,
    }


@mcp.tool
def observe(session_id: str):
    """Screenshot the running app and return a Set-of-Mark image + element list + recent logs.

    The image has numbered boxes over interactive elements; pick an id and pass it
    as `target_id` to `act`.
    """
    session = MANAGER.get(session_id)
    som, elements, logs = session.observe()
    data = {
        "elements": [e.model_dump() for e in elements],
        "logs_since_last": logs,
        "state": session.record.state.value,
    }
    return _result(Image(data=som, format="png"), data)


@mcp.tool
def act(
    session_id: str,
    type: str,
    target_id: int | None = None,
    text: str | None = None,
    key: str | None = None,
    coords: list[int] | None = None,
):
    """Perform one action and return the post-action Set-of-Mark image + `changed` + logs.

    `type` is one of: click, double_click, type, scroll, key, wait.
    Prefer `target_id` (from `observe`) over raw `coords`. The returned image is
    the screen *after* the action — this is verify-after-act.
    """
    session = MANAGER.get(session_id)
    som, changed, logs = session.act(ActionType(type), target_id, text, key, coords)
    return _result(Image(data=som, format="png"), {"changed": changed, "logs": logs})


@mcp.tool
def verify(session_id: str, expectation: str) -> dict:
    """Report whether the deterministic signal contradicts `expectation`.

    This is an error-signal gate, not a full semantic check: it observes the app,
    folds in deterministic findings (crashes/exceptions/console errors), and reports
    whether any blocking error was seen. The host agent should still judge the
    returned screenshot against `expectation` for non-error cases.
    """
    session = MANAGER.get(session_id)
    _som, _elements, logs = session.observe()
    new_findings = detection.scan_logs(logs)
    blocking = [f for f in new_findings if f.severity in (Severity.HIGH, Severity.CRITICAL)]
    accumulated = len(session.record.findings)
    has_signal = bool(new_findings) or accumulated > 0

    return {
        "expectation": expectation,
        "passed": not has_signal,  # only an absence-of-errors signal
        "confidence": "high" if blocking else ("medium" if has_signal else "low"),
        "evidence": {
            "new_error_findings": [f.summary for f in new_findings],
            "session_findings_total": accumulated,
            "recent_logs": logs[-10:],
        },
        "note": "deterministic error signal only — host should also judge the screenshot "
                "against the expectation when no error is found.",
    }


@mcp.tool
def get_findings(session_id: str) -> list:
    """Return the findings collected this session (from the deterministic log tap)."""
    session = MANAGER.get(session_id)
    out = []
    fdir = session.trace.findings_dir
    if os.path.isdir(fdir):
        for name in sorted(os.listdir(fdir)):
            with open(os.path.join(fdir, name)) as f:
                out.append(json.load(f))
    return out


@mcp.tool
def stop(session_id: str) -> dict:
    """Tear down the sandbox (released first), then write the replay (html + video)."""
    out: dict = {"ok": True}
    session = MANAGER.sessions.get(session_id)
    trace_dir = session.trace.dir if session is not None else None
    if session is not None:
        try:
            session.trace.save_session(session.record)
        except Exception:
            pass

    MANAGER.stop(session_id)  # release the billed sandbox BEFORE rendering the replay

    if trace_dir:
        try:
            from .replay import write_replay_html, write_replay_video

            write_replay_video(trace_dir)
            out["replay"] = write_replay_html(trace_dir)
        except Exception:
            pass
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
