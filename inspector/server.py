from __future__ import annotations

import atexit
import json
import os

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from . import detection
from .config import Config
from .models import ActionType, Severity, Surface
from .plan import ScenarioStatus, build_plan
from .session import SessionManager

CONFIG = Config.from_env()
MANAGER = SessionManager(CONFIG)
mcp = FastMCP("Inspector")


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


# --- agentic test-plan orchestration ---

@mcp.tool
def set_plan(session_id: str, goal: str, scenarios: list[dict]) -> dict:
    """Record the overall test plan: the scenarios (app parts/flows/edge cases) to cover.

    Call this after `launch_app` + an initial `observe`, once you've decided what to
    test. Then work the plan scenario-by-scenario. Each scenario is a dict:
    {title, rationale, steps (list), expected}. You can call `set_plan` again to
    adapt the plan as you discover features.
    """
    session = MANAGER.get(session_id)
    session.plan = build_plan(session.record.id, goal, scenarios)
    session.trace.save_plan(session.plan)
    return {
        "plan_id": session.plan.id,
        "scenarios": [
            {"id": s.id, "title": s.title, "status": s.status.value}
            for s in session.plan.scenarios
        ],
        "next": "Work each scenario: observe → act → verify → update_scenario.",
    }


@mcp.tool
def update_scenario(
    session_id: str,
    scenario_id: str,
    status: str,
    notes: str = "",
    finding_ids: list[str] | None = None,
) -> dict:
    """Record a scenario's outcome once you've tested it.

    status ∈ passed | failed | skipped | blocked. Attach any finding ids
    (from `get_findings`) that this scenario surfaced.
    """
    session = MANAGER.get(session_id)
    if session.plan is None:
        return {"error": "no plan set — call set_plan first"}
    scenario = session.plan.get(scenario_id)
    if scenario is None:
        return {"error": f"unknown scenario {scenario_id!r}"}
    scenario.status = ScenarioStatus(status)
    scenario.notes = notes
    if finding_ids:
        scenario.finding_ids = finding_ids
    session.trace.save_plan(session.plan)
    pending = session.plan.pending()
    return {
        "ok": True,
        "remaining": len(pending),
        "next_pending": [{"id": s.id, "title": s.title} for s in pending[:5]],
    }


@mcp.tool
def test_report(session_id: str) -> dict:
    """Return the full test run: per-scenario status + notes + findings, plus totals."""
    session = MANAGER.get(session_id)
    if session.plan is None:
        return {"error": "no plan set"}
    totals: dict = {}
    for s in session.plan.scenarios:
        totals[s.status.value] = totals.get(s.status.value, 0) + 1
    return {
        "goal": session.plan.goal,
        "totals": totals,
        "scenarios": [s.model_dump() for s in session.plan.scenarios],
        "total_findings": len(session.record.findings),
    }


@mcp.prompt
def run_test_session(repo_path: str, goal: str = "test the main user flows") -> str:
    """The agentic loop protocol — drive Inspector as a planning QA agent, not ad-hoc."""
    return f"""You are driving **Inspector** (an MCP that runs the app and gives you eyes + hands) to test an app as an autonomous QA agent. Run a PLAN-DRIVEN loop — don't just poke commands ad-hoc.

Target: `{repo_path}`  ·  Goal: {goal}

1. `launch_app(repo_path="{repo_path}")` and wait until ready.
2. `observe()` — study the Set-of-Mark screenshot + element list; build a model of what the app does.
3. `set_plan(goal="{goal}", scenarios=[...])` — draft 3–7 scenarios covering the DIFFERENT parts: each main flow/form, navigation between views, edge cases, and any AI-powered features. Each scenario: {{title, rationale, steps, expected}}.
4. For each PENDING scenario, run the inner loop:
   a. `observe()` to see the current state.
   b. Decide the next action from the numbered image + element list, then `act(...)`. Re-observe after each action (verify-after-act).
   c. After the key action, `verify(expectation=...)` and `get_findings(...)` to check the expected outcome.
   d. `update_scenario(scenario_id, status=passed|failed|..., notes=..., finding_ids=[...])`.
   e. If you discover new features mid-run, call `set_plan` again to ADAPT the plan.
5. When no PENDING scenarios remain, call `test_report()` and summarize: what passed/failed, the findings (with file:line where available), and recommended fixes.

Plan first, then execute scenario-by-scenario, deciding the next step each time from what you actually observe. Be thorough, but stop once the plan is covered. Never auto-fix-and-merge — report findings for review."""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
