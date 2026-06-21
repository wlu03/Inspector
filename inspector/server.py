from __future__ import annotations

import atexit
import json
import os
import threading

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from . import detection
from .config import Config
from .findings import build_finding
from .models import ActionType, SessionState, Severity, Surface
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


def _bg_launch(session, dev_command: str | None) -> None:
    """Run a launch in the background; record the error for launch_status."""
    try:
        session.launch(dev_command)
    except Exception as exc:  # noqa: BLE001
        session._launch_error = str(exc)[:300]  # state is already ERROR (+ torn down)


@mcp.tool
def launch_app(
    repo_path: str,
    surface: str | None = None,
    dev_command: str | None = None,
    goal: str = "",
    wait: bool = True,
) -> dict:
    """Boot the app in a sandbox and (by default) wait until it's interactive.

    Detects the framework/dev command and launches it on the right surface.
    Returns the session_id used by the other tools. On failure the sandbox is torn
    down so nothing is leaked.

    Cold boot can take 30-120s (deps + browser + dev server). Pass `wait=false` to
    return immediately with `state="launching"` and poll `launch_status(session_id)`
    until `ready` — avoids host tool-call timeouts on a real cold boot.
    """
    surf = Surface(surface) if surface else None
    session = MANAGER.create(repo_path, surf, goal)
    sid = session.record.id

    if not wait:
        threading.Thread(
            target=_bg_launch, args=(session, dev_command),
            name=f"launch-{sid}", daemon=True,
        ).start()
        return {
            "session_id": sid,
            "surface": session.record.surface.value,
            "state": session.record.state.value,
            "ready": None,
            "task_id": session.record.task_id or sid,
            "note": "launching in background — poll launch_status(session_id) until ready",
        }

    try:
        ready = session.launch(dev_command)
    except Exception as exc:
        MANAGER.stop(sid)  # kill the sandbox, drop the session
        return {
            "session_id": sid,
            "surface": session.record.surface.value,
            "state": "error",
            "ready": False,
            "error": str(exc)[:300],
        }
    return {
        "session_id": sid,
        "surface": session.record.surface.value,
        "state": session.record.state.value,
        "ready": ready,
    }


@mcp.tool
def launch_status(session_id: str) -> dict:
    """Poll a background launch (from `launch_app(wait=false)`).

    Returns the current state and `ready=true` once the app is interactive. On a
    failed launch, `ready=false` and `error` carries the reason.
    """
    session = MANAGER.get(session_id)
    state = session.record.state
    out = {
        "session_id": session_id,
        "surface": session.record.surface.value,
        "state": state.value,
        "ready": state == SessionState.READY,
    }
    if session._launch_error:
        out["error"] = session._launch_error
    return out


@mcp.tool
def observe(session_id: str, include_image: bool = True):
    """Screenshot the running app and return a Set-of-Mark image + element list + recent logs.

    The image has numbered boxes over interactive elements; pick an id and pass it
    as `target_id` to `act`. Each element carries its id/label/role/bbox, so you can
    ground from the text list alone. Set `include_image=false` (or hit the per-session
    image cap) to get text only and save host tokens.
    """
    session = MANAGER.get(session_id)
    som, elements, logs = session.observe()
    data = {
        "elements": [e.model_dump() for e in elements],
        "logs_since_last": logs,
        "state": session.record.state.value,
    }
    if include_image and session.image_allowed():
        return _result(Image(data=som, format="png"), data)
    data["image_omitted"] = "text-only (set include_image=true or raise max_images_per_session)"
    return data


@mcp.tool
def act(
    session_id: str,
    type: str,
    target_id: int | None = None,
    text: str | None = None,
    key: str | None = None,
    coords: list[int] | None = None,
    include_image: bool = True,
):
    """Perform one action and return the post-action Set-of-Mark image + `changed` + logs.

    `type` is one of: click, double_click, type, scroll, key, wait.
    Prefer `target_id` (from `observe`) over raw `coords`. The returned image is
    the screen *after* the action — this is verify-after-act. Set `include_image=false`
    (or hit the per-session image cap) to get `changed`+logs only and save host tokens.
    """
    session = MANAGER.get(session_id)
    som, changed, logs = session.act(ActionType(type), target_id, text, key, coords)
    data = {"changed": changed, "logs": logs}
    if include_image and session.image_allowed():
        return _result(Image(data=som, format="png"), data)
    data["image_omitted"] = "text-only (set include_image=true or raise max_images_per_session)"
    return data


@mcp.tool
def verify(session_id: str, expectation: str):
    """Observe the app and report whether a NEW error signal appeared, with a screenshot.

    Error-signal gate, not a full semantic check: it returns the current Set-of-Mark
    screenshot plus whether any deterministic error (crash/exception/console error)
    surfaced *since the last verify* — so an earlier unrelated finding doesn't pin
    every later check to failed. Judge the returned screenshot against `expectation`
    for non-error cases.
    """
    session = MANAGER.get(session_id)
    som, _elements, logs = session.observe()

    # Only findings new since the last verify count as a fresh signal.
    total = len(session.record.findings)
    new_count = total - session._verified_count
    session._verified_count = total

    # Severity of the just-observed window (current state, not history).
    window = detection.scan_logs(logs)
    blocking = [f for f in window if f.severity in (Severity.HIGH, Severity.CRITICAL)]
    has_new_signal = new_count > 0 or bool(window)

    data = {
        "expectation": expectation,
        "passed": not has_new_signal,
        "confidence": "high" if blocking else ("medium" if has_new_signal else "low"),
        "evidence": {
            "new_findings_since_last_verify": new_count,
            "current_error_logs": [f.summary for f in window],
            "session_findings_total": total,
            "recent_logs": logs[-10:],
        },
        "note": "deterministic error signal only — also judge the returned screenshot "
                "against the expectation.",
    }
    return _result(Image(data=som, format="png"), data)


@mcp.tool
def report_issue(
    session_id: str,
    summary: str,
    severity: str = "medium",
    expected: str = "",
    actual: str = "",
    suspected_area: str = "",
    repro: list[str] | None = None,
    screenshot_ref: str | None = None,
) -> dict:
    """File a finding the HOST agent judged from the screenshot (host-as-brain).

    The host sees what the deterministic log-tap can't — wrong layout, a missing
    element, bad copy, an action that silently did nothing. This records a structured
    Finding into the session trace so it shows up in get_findings / test_report /
    the replay alongside the auto-detected ones. severity ∈ low|medium|high|critical.
    """
    session = MANAGER.get(session_id)
    sev = {s.value: s for s in Severity}.get(severity.lower(), Severity.MEDIUM)
    finding = build_finding(
        session_id=session.record.id,
        trace_id=session.record.trace_id,
        summary=summary[:300],
        expected=expected,
        actual=actual,
        suspected_area=suspected_area or "(host-reported)",
        severity=sev,
        repro=repro or session.action_log[-4:],
        screenshot_refs=[screenshot_ref] if screenshot_ref else [],
    )
    session.trace.save_finding(finding)
    session.record.findings.append(finding.id)
    return {
        "finding_id": finding.id,
        "trace_id": session.record.trace_id,
        "severity": sev.value,
        "total_findings": len(session.record.findings),
    }


@mcp.tool
def update_finding_status(session_id: str, finding_id: str, status: str) -> dict:
    """Record fix-loop progress on a finding: open | fixed | verified | dismissed.

    Mark a finding `fixed` after editing the code, then `verified` once a re-run no
    longer reproduces it — closing the find → fix → re-verify loop. (Re-verify by
    re-running the app and checking the signature is gone — e.g. a fresh `test_app`
    run or `inspector.eval`.)
    """
    valid = {"open", "fixed", "verified", "dismissed"}
    if status not in valid:
        return {"error": f"status must be one of {sorted(valid)}"}
    session = MANAGER.get(session_id)
    fdir = session.trace.findings_dir
    if os.path.isdir(fdir):
        for name in os.listdir(fdir):
            path = os.path.join(fdir, name)
            try:
                with open(path) as f:
                    data = json.load(f)
            except Exception:
                continue
            if data.get("id") == finding_id:
                data["status"] = status
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
                return {"finding_id": finding_id, "status": status}
    return {"error": f"unknown finding {finding_id!r}"}


@mcp.tool
def audit_dom(session_id: str) -> dict:
    """Run a DETERMINISTIC DOM audit (web/Electron) and file any issues as findings.

    The strongest evidence tier — structured facts read straight off the live DOM,
    not a vision judgment: axe-core WCAG violations, broken images (naturalWidth=0),
    and form inputs with no accessible label. Each issue is recorded as a Finding
    (shows up in get_findings / test_report / the replay). Returns the raw counts.
    No-ops (empty) on surfaces without a DOM. Use this in your accessibility/coverage
    scenarios — it catches what the screenshot can't.
    """
    session = MANAGER.get(session_id)
    audit, new_ids = session.audit()
    return {
        "axe_violations": audit.get("axe_violations", []),
        "broken_images": audit.get("broken_images", []),
        "unlabeled_inputs": audit.get("unlabeled_inputs", []),
        "new_findings": new_ids,
        "total_findings": len(session.record.findings),
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


def _stop_and_replay(session_id: str) -> dict:
    """Persist the session, release the billed sandbox, then render the replay."""
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


@mcp.tool
def stop(session_id: str) -> dict:
    """Tear down the sandbox (released first), then write the replay (html + video)."""
    return _stop_and_replay(session_id)


@mcp.tool
def test_app(
    repo_path: str,
    goal: str = "exercise the main user flows and find bugs",
    surface: str | None = None,
    dev_command: str | None = None,
    max_steps: int | None = None,
) -> dict:
    """ONE CALL: launch the app in a VM, autonomously explore it, and return the bugs found.

    This is the hands-free entry point — it does internally what the granular
    tools do step-by-step. It boots the app in a sandbox, then loops
    observe → (embedded driver model picks the next action) → act, judging each
    step for crashes/console errors/broken behavior, until the driver decides it's
    seen enough or a LoopGuard tripwire (max steps / wall-clock / no-progress)
    fires. Always tears the sandbox down and writes a replay. Never auto-fixes —
    it reports reproducible findings for review.
    """
    from .autopilot import collect_findings, run_autopilot
    from .driver import get_driver

    surf = Surface(surface) if surface else None
    session = MANAGER.create(repo_path, surf, goal)
    sid = session.record.id

    try:
        ready = session.launch(dev_command)
    except Exception as exc:
        result = _stop_and_replay(sid)
        return {
            "session_id": sid, "surface": session.record.surface.value,
            "ready": False, "error": str(exc)[:300],
            "findings": [], "findings_total": 0, **result,
        }

    if not ready:
        # launch came up not-ready; still surface any deterministic findings + replay.
        findings = collect_findings(session)
        result = _stop_and_replay(sid)
        return {
            "session_id": sid, "surface": session.record.surface.value,
            "ready": False, "error": "app never became interactive",
            "findings": findings, "findings_total": len(findings), **result,
        }

    try:
        driver = get_driver(CONFIG)
        report = run_autopilot(session, driver, goal, max_steps)
    except Exception as exc:
        findings = collect_findings(session)
        result = _stop_and_replay(sid)
        return {
            "session_id": sid, "surface": session.record.surface.value,
            "ready": True, "error": str(exc)[:300],
            "findings": findings, "findings_total": len(findings), **result,
        }

    result = _stop_and_replay(sid)  # teardown + replay AFTER the loop finishes
    return {
        "session_id": sid,
        "surface": session.record.surface.value,
        "ready": True,
        **report,
        **result,
    }


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
    """The agentic loop protocol — drive Inspector as an adversarial QA agent, not ad-hoc."""
    from .adversarial import catalog_text

    return f"""You are driving **Inspector** (an MCP that runs the app and gives you eyes + hands) to test an app as an autonomous QA agent. Your job is to **TRY TO BREAK the app, not confirm it works.** Run a PLAN-DRIVEN loop — don't just poke commands ad-hoc.

Target: `{repo_path}`  ·  Goal: {goal}

1. `launch_app(repo_path="{repo_path}")` and wait until ready.
2. `observe()` — study the Set-of-Mark screenshot + element list; build a model of what the app does.
3. **PLAN IN THREE ROUNDS in your head, then `set_plan(goal="{goal}", scenarios=[...])`:**
   • **Round 1 — Functional:** the core user flows (action → expected result).
   • **Round 2 — Adversarial:** re-examine Round 1 for what could BREAK it — error paths, empty states, race conditions (rapid double-submit), edge inputs (empty, invalid, 500+ chars, special/unicode, `<script>`/SQL injection), and different roles.
   • **Round 3 — Coverage:** accessibility (`audit_dom`), keyboard-only nav, a bogus route (404), narrow/mobile viewport, console errors, visual consistency.
   Dedupe across the three rounds into 4–8 scenarios. Each: {{title, rationale, steps, expected}}.
4. For each PENDING scenario, run the inner loop:
   a. `observe()` to see the current state.
   b. Decide the next action from the numbered image + element list, **preferring the adversarial move over the happy path**, then `act(...)`. Re-observe after each action (verify-after-act).
   c. After the key action, `verify(expectation=...)` and `get_findings(...)`. For web/Electron, call `audit_dom()` to collect deterministic a11y / broken-image / unlabeled-input findings the screenshot can't show.
   d. `update_scenario(scenario_id, status=passed|failed|..., notes=..., finding_ids=[...])`.
   e. If you discover new features mid-run, call `set_plan` again to ADAPT the plan.
5. When no PENDING scenarios remain, `report_issue(...)` anything you SAW that the log tap missed, then `test_report()` and summarize: what passed/failed, the findings (with file:line where available), and recommended fixes.

ADVERSARIAL MOVES TO TRY (consult per element type):
{catalog_text()}

Plan first, then execute scenario-by-scenario, deciding the next step each time from what you actually observe. Be thorough, but stop once the plan is covered. Never auto-fix-and-merge — report findings for review."""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
