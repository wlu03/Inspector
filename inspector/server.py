from __future__ import annotations

import atexit
import functools
import json
import logging
import os
import threading
from typing import TypedDict

import anyio
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image
from mcp.types import ToolAnnotations

from . import detection
from .assertions import Assertion, AssertionKind, evaluate_assertions, summarize
from .config import Config
from .findings import build_finding, build_repro_spec
from .models import ActionType, SessionState, Severity, Surface
from .plan import ScenarioStatus, build_plan
from .session import SessionManager

CONFIG = Config.from_env()
MANAGER = SessionManager(CONFIG)

INSTRUCTIONS = (
    "Inspector drives a real running app so a coding agent can see, operate, and test "
    "it across web / Electron / Android / iOS, returning reproducible, source-linked "
    "findings.\n\n"
    "Typical flow:\n"
    "1. launch_app(repo_path[, surface, dev_command]) -> session_id  (or test_app for a "
    "one-call autonomous run).\n"
    "2. observe(session_id) -> Set-of-Mark screenshot + numbered elements + logs.\n"
    "3. act(session_id, target_id=..., ...) using an element id from observe.\n"
    "4. check(session_id, expectation) for new runtime errors (failed | unknown); audit_dom for "
    "deterministic a11y / broken-image / unlabeled-input findings (web/Electron).\n"
    "5. get_findings(session_id) for evidence-backed results.\n"
    "6. stop(session_id) to tear down the sandbox and write the replay (returns a "
    "dashboard link).\n\n"
    "Fix loop: fix_finding / verify_fix / bug_ledger. Devin auto-fix: fix_with_devin / "
    "devin_status. Cross-run history: list_runs / get_run and the inspector://sessions "
    "resources.\n\n"
    "Setup: only REPLICATE_API_TOKEN (the detector) is required; E2B is optional. Host "
    "execution is refused over the HTTP transport without INSPECTOR_ALLOW_UNSAFE_LOCAL."
)
mcp = FastMCP("Inspector", instructions=INSTRUCTIONS)
log = logging.getLogger("inspector")

# Tool annotation presets so hosts (Claude Code) can auto-approve safe tools and only
# prompt on the ones with real side effects. READ_ONLY = no mutation (auto-approve);
# WRITE = mutates the trace/app but cheap/safe; DESTRUCTIVE = spins or tears a *billed*
# sandbox → worth a confirmation prompt.
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
# EXTERNAL = reaches a third-party service (Devin) and records its result — not read-only.
EXTERNAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)

# Default 'core' tool surface (INSPECTOR_PROFILE=core). The rest are advanced/admin
# tools, hidden unless INSPECTOR_PROFILE=full.
CORE_TOOLS = frozenset({
    "launch_app", "launch_status", "observe", "act", "check", "audit_dom",
    "report_issue", "get_findings", "stop", "test_app", "check_assertions",
})
ADVANCED_TOOLS = frozenset({
    "update_finding_status", "open_dashboard", "build_dashboard", "list_runs",
    "get_run", "fix_finding", "verify_fix", "bug_ledger", "fix_with_devin",
    "devin_status", "test_app_parallel", "test_feature", "set_plan",
    "update_scenario", "test_report",
})

def _apply_profile() -> None:
    """core profile hides the advanced/admin tools from MCP clients; full exposes all."""
    if CONFIG.profile in ("full", "advanced", "all"):
        return
    for _name in ADVANCED_TOOLS:
        try:
            _provider = getattr(mcp, "local_provider", None)
            if _provider is not None and hasattr(_provider, "remove_tool"):
                _provider.remove_tool(_name)
            else:
                mcp.remove_tool(_name)
        except Exception:
            pass


def _friendly(fn):
    """Turn a raw KeyError from an unknown/expired session_id into a usable dict.

    Wraps the live-session tools so the host gets {error, active_sessions, hint}
    instead of an ugly stack trace + a dead turn.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyError as exc:
            with MANAGER._lock:
                active = list(MANAGER.sessions.keys())
            return {
                "error": "unknown or expired session",
                "detail": str(exc).strip('"'),
                "active_sessions": active,
                "hint": "call launch_app or test_app to start one "
                        "(or list_runs / get_run for past runs on disk)",
            }
        except Exception as exc:  # noqa: BLE001
            # Surface a real MCP tool error (isError=true) instead of a success-shaped
            # {"error": ...} dict. FastMCP returns it as an error result — the host sees
            # the failure and can recover; it does not crash the turn.
            raise ToolError(f"tool failed: {str(exc)[:300]}") from exc
    return wrapper


async def _run_with_heartbeat(ctx, label: str, fn):
    """Run blocking `fn` off the event loop, emitting a liveness heartbeat until done.

    Turns a 30–120s frozen tool call into streamed progress ("still working (Ns)")
    so the user sees the cold boot is alive. Re-raises whatever `fn` raises.
    """
    state: dict = {}

    async def runner():
        try:
            state["result"] = await anyio.to_thread.run_sync(fn)
        except BaseException as exc:  # noqa: BLE001 - surfaced after the group
            state["error"] = exc

    async with anyio.create_task_group() as tg:
        tg.start_soon(runner)
        ticks = 0
        while "result" not in state and "error" not in state:
            await anyio.sleep(3)
            ticks += 1
            if ctx is not None:
                try:
                    await ctx.report_progress(progress=min(10 + ticks * 7, 95), total=100)
                    await ctx.info(f"{label}… still working ({ticks * 3}s)")
                except Exception:
                    pass
    if "error" in state:
        raise state["error"]
    return state.get("result")


async def _say(ctx, message: str, progress: int | None = None) -> None:
    """Best-effort ctx.info + optional progress (no-op if the client can't receive)."""
    if ctx is None:
        return
    try:
        await ctx.info(message)
        if progress is not None:
            await ctx.report_progress(progress=progress, total=100)
    except Exception:
        pass


@atexit.register
def _cleanup_all() -> None:
    """Best-effort teardown of every live sandbox on process exit."""
    for sid in list(MANAGER.sessions.keys()):
        try:
            MANAGER.stop(sid)
        except Exception:
            log.warning("cleanup teardown failed for %s", sid, exc_info=True)


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
        session._launch_error = str(exc)[:300]
        # ensure the billed sandbox is released even if launch() raised before its own
        # teardown ran (e.g. sandbox.start() itself failed) — the sync path does this too.
        try:
            MANAGER.stop(session.record.id)
        except Exception:
            pass


def _live_sessions() -> dict:
    """Currently-running sessions for the dashboard's live feed (GET /live.json).

    Read straight off the live SessionManager — findings/frames grow during a run,
    so the dashboard can show in-progress work mid-run (the static files only update
    when the run ends).
    """
    with MANAGER._lock:
        sessions = list(MANAGER.sessions.values())
    out = []
    for s in sessions:
        rec = s.record
        out.append({
            "id": rec.id,
            "alias": rec.alias,
            "surface": rec.surface.value,
            "goal": rec.goal,
            "state": rec.state.value,
            "findings": len(rec.findings),
            "frames": getattr(s.trace, "_frame_n", 0),
            "created_at": rec.created_at,
        })
    return {"sessions": out}


def _rebuild_dashboard() -> None:
    """Re-render the static dashboard so a status change shows up immediately."""
    try:
        from .dashboard import build_dashboard

        build_dashboard(CONFIG.trace_root)
    except Exception:
        log.warning("dashboard rebuild failed", exc_info=True)


def _devin_fix(signature: str) -> dict:
    """Start a Devin fix for one ledger issue, then refresh the dashboard."""
    from . import devin

    out = devin.fix_with_devin(CONFIG, CONFIG.trace_root, signature)
    if not out.get("error"):
        _rebuild_dashboard()
    return out


def _devin_poll(devin_session_id: str) -> dict:
    """Poll a Devin session; refresh the dashboard if a PR landed."""
    from . import devin

    out = devin.poll_devin(CONFIG, CONFIG.trace_root, devin_session_id)
    if out.get("pr_url"):
        _rebuild_dashboard()
    return out


def _resolve_signature(body: dict) -> str | None:
    """A bug signature from an explicit `signature` OR a `session_id`+`finding_id` —
    so any surfaced finding (a replay card, not just a ledger row) can launch Devin."""
    sig = body.get("signature")
    if not sig and body.get("session_id") and body.get("finding_id"):
        from .dashboard.aggregate import signature_for_finding
        sig = signature_for_finding(CONFIG.trace_root, body["session_id"], body["finding_id"])
    return sig


def _dashboard_action(path: str, body: dict) -> dict:
    """Dispatch dashboard POST /api/* actions (the Fix with Devin button)."""
    if path == "/api/devin-fix":
        sig = _resolve_signature(body)
        return _devin_fix(sig) if sig else {"error": "missing signature or session_id+finding_id"}
    if path == "/api/devin-status":
        sid = body.get("devin_session_id") or body.get("session_id")
        return _devin_poll(sid) if sid else {"error": "missing devin_session_id"}
    return {"error": f"unknown action {path}"}


def _dashboard_links(session_id: str | None = None) -> dict:
    """Rebuild + serve the dashboard, return a clickable localhost link for the run.

    Folded into every test-finishing tool so the user lands on the replay of what the
    agent just surfaced. Degrades quietly (returns {}) if the server can't start.
    """
    try:
        from .dashboard import serve as _serve

        _serve.set_live_provider(_live_sessions)  # power the live feed
        _serve.set_action_handler(_dashboard_action)  # power the Fix with Devin button
        publish = _serve.publish

        links = publish(CONFIG.trace_root, session_id, CONFIG.dashboard_port)
        url = links.get("dashboard_url", "")
        links["view"] = f"✅ Test session complete. View what the agent surfaced → {url}"

        # surface the fix-loop delta vs the previous run of this repo
        from .dashboard.aggregate import latest_update
        upd = latest_update(CONFIG.trace_root)
        if upd.get("has_prev"):
            fixed, new = len(upd.get("verified", [])), len(upd.get("new", []))
            links["update"] = {"fixed_since_last_run": fixed, "new": new,
                               "still_open": len(upd.get("still_open", []))}
            if fixed or new:
                links["view"] += f"  ·  {fixed} fixed since last run, {new} new (see Bug Ledger tab)"
        return links
    except Exception as exc:  # noqa: BLE001
        log.warning("dashboard publish failed", exc_info=True)
        return {"dashboard_error": str(exc)[:200]}


# --- typed tool outputs: schemas MCP clients see; tools still return plain dicts ---
class SessionResult(TypedDict, total=False):
    session_id: str
    alias: str | None
    surface: str
    state: str
    ready: bool | None
    task_id: str
    note: str
    error: str


class ObserveResult(TypedDict, total=False):
    elements: list[dict]
    logs_since_last: list[str]
    state: str
    image_omitted: str


class ActResult(TypedDict, total=False):
    changed: bool
    logs: list[str]


class CheckResult(TypedDict, total=False):
    expectation: str
    status: str
    confidence: str
    evidence: dict
    note: str


class AssertionsOut(TypedDict, total=False):
    overall: str
    counts: dict
    results: list[dict]


class ReportIssueResult(TypedDict, total=False):
    finding_id: str
    trace_id: str
    severity: str
    total_findings: int


class AuditResult(TypedDict, total=False):
    axe_violations: list
    broken_images: list
    unlabeled_inputs: list
    new_findings: list[str]
    total_findings: int


class StopResult(TypedDict, total=False):
    ok: bool
    replay: str
    dashboard_url: str
    replay_url: str
    view: str


class TestAppResult(TypedDict, total=False):
    session_id: str
    alias: str | None
    surface: str
    ready: bool
    error: str
    findings: list[dict]
    findings_total: int
    dashboard_url: str
    view: str


@mcp.tool(annotations=DESTRUCTIVE)
async def launch_app(
    repo_path: str,
    surface: str | None = None,
    dev_command: str | None = None,
    goal: str = "",
    wait: bool = True,
    alias: str | None = None,
    ctx: Context = None,
) -> SessionResult:
    """Boot the app in a sandbox and (by default) wait until it's interactive.

    Detects the framework/dev command and launches it on the right surface.
    Returns the session_id used by the other tools. On failure the sandbox is torn
    down so nothing is leaked. Pass `alias` to give the run a human name (e.g.
    "checkout-flow") usable in place of the session_id in later tools.

    Cold boot can take 30-120s (deps + browser + dev server); progress is streamed.
    Pass `wait=false` to return immediately with `state="launching"` and poll
    `launch_status(session_id)` until `ready`.
    """
    surf = Surface(surface) if surface else None
    session = MANAGER.create(repo_path, surf, goal, alias=alias)
    sid = session.record.id

    if not wait:
        threading.Thread(
            target=_bg_launch, args=(session, dev_command),
            name=f"launch-{sid}", daemon=True,
        ).start()
        return {
            "session_id": sid, "alias": session.record.alias,
            "surface": session.record.surface.value,
            "state": session.record.state.value,
            "ready": None,
            "task_id": session.record.task_id or sid,
            "note": "launching in background — poll launch_status(session_id) until ready",
        }

    await _say(ctx, "Booting sandbox — cold boot can take 30–120s (deps + browser + dev server)…", 5)
    try:
        ready = await _run_with_heartbeat(ctx, "Launching", lambda: session.launch(dev_command))
    except BaseException as exc:
        MANAGER.stop(sid)  # always release the billed sandbox, even on cancellation
        if not isinstance(exc, Exception):
            raise  # propagate cancellation/interrupt AFTER tearing the sandbox down
        await _say(ctx, f"launch failed: {str(exc)[:120]}")
        return {
            "session_id": sid, "alias": session.record.alias,
            "surface": session.record.surface.value,
            "state": "error", "ready": False, "error": str(exc)[:300],
        }
    await _say(ctx, "ready" if ready else "launched but not interactive", 100)
    return {
        "session_id": sid, "alias": session.record.alias,
        "surface": session.record.surface.value,
        "state": session.record.state.value,
        "ready": ready,
    }


@mcp.tool(annotations=READ_ONLY)
@_friendly
def launch_status(session_id: str) -> SessionResult:
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


@mcp.tool(annotations=READ_ONLY)
@_friendly
def observe(session_id: str, include_image: bool = True) -> ObserveResult:
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


@mcp.tool(annotations=WRITE)
@_friendly
def act(
    session_id: str,
    type: str,
    target_id: int | None = None,
    text: str | None = None,
    key: str | None = None,
    coords: list[int] | None = None,
    include_image: bool = True,
) -> ActResult:
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


@mcp.tool(annotations=WRITE)
@_friendly
def check(session_id: str, expectation: str) -> CheckResult:
    """Check for NEW runtime errors and return a screenshot. Three-valued; never a false pass.

    Returns status="failed" when a fresh deterministic error (crash, exception, or
    console error) surfaced since the last check, else status="unknown" (no runtime
    error appeared, but this tool cannot confirm a VISUAL expectation). The caller
    judges the returned Set-of-Mark screenshot against `expectation` to decide a real
    pass. Only findings new since the last check count, so an earlier unrelated finding
    does not pin every later check to failed.
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
        "status": "failed" if has_new_signal else "unknown",
        "confidence": "high" if blocking else ("medium" if has_new_signal else "low"),
        "evidence": {
            "new_findings_since_last_verify": new_count,
            "current_error_logs": [f.summary for f in window],
            "session_findings_total": total,
            "recent_logs": logs[-10:],
        },
        "note": "runtime-error gate only. 'failed' = a new error surfaced; 'unknown' = "
                "no new error, but the visual expectation is NOT confirmed. Judge the "
                "returned screenshot against the expectation to decide a real pass.",
    }
    return _result(Image(data=som, format="png"), data)


def _assertion_context(session, parsed: list[Assertion]) -> dict:
    """Gather the observation channels the assertions need: visible text, elements,
    the current URL (CDP surfaces), and control-state for any referenced elements."""
    _som, elements, _logs = session.observe()
    texts = [e.label for e in elements if e.label]
    try:
        texts += [t.label for t in session.adapter.text_elements() if t.label]
    except Exception:
        pass
    el_dicts = [{"label": e.label, "role": e.role} for e in elements]
    url = None
    cdp = getattr(session.adapter, "cdp", None)
    if cdp is not None:
        try:
            v = cdp.evaluate("window.location.href")
            url = v.strip('"') if isinstance(v, str) else v
        except Exception:
            url = None
    need = {a.on.lower() for a in parsed
            if a.kind in (AssertionKind.VALUE, AssertionKind.STATE) and a.on}
    states: dict = {}
    if need:
        for e in elements:
            lab = (e.label or "").lower()
            if lab in need and lab not in states:
                try:
                    states[lab] = session.adapter.control_state(e.id)
                except Exception:
                    pass
    return {"texts": texts, "elements": el_dicts, "url": url, "states": states}


@mcp.tool(annotations=WRITE)
@_friendly
def check_assertions(session_id: str, assertions: list[Assertion]) -> AssertionsOut:
    """Evaluate typed assertions against the live app: each pass | fail | inconclusive.

    Unlike `check` (a runtime-error gate), this actually evaluates expectations. Each
    assertion has {kind, target, op, expected, on}: kind in text | role | value | count
    | url | state | network | screenshot; op in present | absent | equals | contains |
    gte | lte. A channel that isn't available (network/screenshot, a missing element, no
    URL on this surface) returns `inconclusive` with a reason, never a false pass.
    Returns per-assertion results with evidence plus an `overall` verdict.
    """
    session = MANAGER.get(session_id)
    ctx = _assertion_context(session, assertions)
    results = evaluate_assertions(assertions, **ctx)
    return {"results": [r.model_dump() for r in results], **summarize(results)}


@mcp.tool(annotations=WRITE)
@_friendly
def report_issue(
    session_id: str,
    summary: str,
    severity: str = "medium",
    expected: str = "",
    actual: str = "",
    suspected_area: str = "",
    repro: list[str] | None = None,
    screenshot_ref: str | None = None,
) -> ReportIssueResult:
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
    finding.repro_spec = build_repro_spec(session)
    session.trace.save_finding(finding)
    session.record.findings.append(finding.id)
    return {
        "finding_id": finding.id,
        "trace_id": session.record.trace_id,
        "severity": sev.value,
        "total_findings": len(session.record.findings),
    }


@mcp.tool(annotations=WRITE)
def update_finding_status(session_id: str, finding_id: str, status: str) -> dict:
    """Record fix-loop progress on a finding: open | fixed | verified | dismissed.

    Mark a finding `fixed` after editing the code, then `verified` once a re-run no
    longer reproduces it — closing the find → fix → re-verify loop. (Re-verify by
    re-running the app and checking the signature is gone — e.g. a fresh `test_app`
    run or `inspector.eval`.) Works on any session on disk, live or long-finished —
    so the dashboard fix loop can sign off past runs too.
    """
    from .dashboard.aggregate import update_finding_status as _update
    return _update(CONFIG.trace_root, session_id, finding_id, status)


@mcp.tool(annotations=WRITE)
@_friendly
def audit_dom(session_id: str) -> AuditResult:
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


@mcp.tool(annotations=READ_ONLY)
@_friendly
def get_findings(session_id: str) -> list[dict]:
    """Return the findings collected this session (from the deterministic log tap)."""
    session = MANAGER.get(session_id)
    out = []
    fdir = session.trace.findings_dir
    if os.path.isdir(fdir):
        for name in sorted(os.listdir(fdir)):
            with open(os.path.join(fdir, name)) as f:
                out.append(json.load(f))
    return out


# --- dashboard & cross-session fix loop ---

@mcp.tool(annotations=WRITE)
def open_dashboard(session_id: str | None = None) -> dict:
    """Build + serve the dashboard on localhost and return a clickable link.

    Aggregates every past session into one replayable dashboard, starts a local
    server (http://127.0.0.1:<dashboard_port>), and returns `dashboard_url`. Pass a
    `session_id` to deep-link straight to that run (the row is highlighted) and also
    get a `replay_url`. This is what to hand the user after a test finishes so they
    can view what the agent surfaced.
    """
    return _dashboard_links(session_id)


@mcp.tool(annotations=WRITE)
def build_dashboard() -> dict:
    """Aggregate EVERY past session into one static, replayable dashboard + serve it.

    Scans the trace tree (~/.inspector/sessions), ensures each session has a replay,
    writes one dashboard.html (+ dashboard.json) rolling up findings/pass-rate/recurring
    bugs, starts the localhost server, and returns the clickable `dashboard_url`.
    """
    from .dashboard.aggregate import aggregate_stats, scan_sessions

    links = _dashboard_links()
    return {**links, **aggregate_stats(scan_sessions(CONFIG.trace_root))}


@mcp.tool(annotations=READ_ONLY)
def list_runs(limit: int = 50) -> dict:
    """List past Inspector sessions (newest first) with verdict + findings + replay path.

    The cross-session history behind the dashboard: surface, goal, pass/fail, finding
    counts by severity, and where each run's replay lives.
    """
    from .dashboard.aggregate import aggregate_stats, scan_sessions

    summaries = scan_sessions(CONFIG.trace_root)
    return {"stats": aggregate_stats(summaries), "runs": summaries[:limit]}


@mcp.tool(annotations=READ_ONLY)
def get_run(session_id: str) -> dict:
    """Full detail for one past session: meta, plan, findings (with fix prompts), counts."""
    from .dashboard.aggregate import load_session_detail

    detail = load_session_detail(CONFIG.trace_root, session_id)
    if not detail["session"]:
        return {"error": f"no session {session_id!r} on disk"}
    return {
        "session": detail["session"],
        "run": detail["run"],
        "plan": detail.get("plan") or {},
        "findings": detail["findings"],
        "n_actions": len(detail["actions"]),
        "n_frames": len(detail["frames"]),
    }


@mcp.tool(annotations=READ_ONLY)
def fix_finding(session_id: str, finding_id: str) -> dict:
    """Get the actionable fix context for one finding — the live agent fix loop.

    Returns the finding plus a ready-to-apply fix prompt (summary, expected vs actual,
    suspected file:line, repro, evidence). The host agent edits the code, marks the
    finding `fixed` via update_finding_status, and re-runs (test_app) to verify it's
    gone — then marks it `verified`.
    """
    from .dashboard.aggregate import load_session_detail

    detail = load_session_detail(CONFIG.trace_root, session_id)
    if not detail["session"]:
        return {"error": f"no session {session_id!r} on disk"}
    finding = next((f for f in detail["findings"] if f.get("id") == finding_id), None)
    if finding is None:
        return {"error": f"unknown finding {finding_id!r} in session {session_id!r}"}
    return {
        "finding": finding,
        "fix_prompt": finding.get("fix_prompt", ""),
        "suspected_area": finding.get("suspected_area", ""),
        "next": "edit the code, then update_finding_status(session_id, finding_id, 'fixed') "
                "and re-run test_app to verify; mark 'verified' once it no longer reproduces.",
    }


@mcp.tool(annotations=DESTRUCTIVE)
async def verify_fix(session_id: str, finding_id: str, ctx: Context = None) -> dict:
    """Re-verify ONE finding is fixed by replaying its exact repro on the current build.

    Faster + more targeted than a full test_app re-run: it re-launches the app, replays
    the finding's repro (its ReproSpec by semantic locator, else coordinates), and reports whether the signature
    reappears (still_present) or is gone (fixed) — then stamps the finding accordingly.
    Use after editing the code (or after fix_with_devin) to confirm the fix worked.
    """
    from .dashboard.aggregate import load_session_detail
    from .reverify import mark_fixed
    from .reverify import verify_fix as _verify_fix

    detail = load_session_detail(CONFIG.trace_root, session_id)
    sess = detail.get("session") or {}
    if not sess:
        return {"error": f"no session {session_id!r} on disk"}
    finding = next((f for f in detail["findings"] if f.get("id") == finding_id), None)
    if finding is None:
        return {"error": f"unknown finding {finding_id!r} in session {session_id!r}"}

    repo = sess.get("repo_path")
    prior_dir = os.path.join(CONFIG.trace_root, session_id)
    surface = Surface(sess["surface"]) if sess.get("surface") else None
    summary = finding.get("summary", "")

    spec = None
    rs = finding.get("repro_spec")
    if rs:
        from .models import ReproSpec
        try:
            spec = ReproSpec.model_validate(rs)
        except Exception:
            spec = None

    if spec and spec.steps:
        from .reverify import verify_fix_spec
        res = await _run_with_heartbeat(
            ctx, "re-verifying (repro spec)",
            lambda: verify_fix_spec(CONFIG, repo, spec, summary, surface),
        )
    else:
        res = await _run_with_heartbeat(
            ctx, "re-verifying fix",
            lambda: _verify_fix(CONFIG, repo, prior_dir, summary, surface),
        )
    if res.get("status") in ("fixed", "still_present"):
        mark_fixed(prior_dir, summary, fixed=res["status"] == "fixed")
    res["finding_id"] = finding_id
    return res


@mcp.tool(annotations=READ_ONLY)
def bug_ledger() -> dict:
    """Every unique issue across all runs with its CURRENT fix status — the fix loop, closed.

    Status is evidence-based: an issue gone from a repo's latest run is `verified` (it no
    longer reproduces = fixed); one still present is `open`. Also returns `update` — what
    changed in the most recent run (fixed since last run / new / still-open). This is the
    Bug Ledger tab on the dashboard: re-run after a fix and the issue flips to verified.
    """
    from .dashboard.aggregate import bug_ledger as _ledger
    from .dashboard.aggregate import latest_update

    ledger = _ledger(CONFIG.trace_root)
    return {
        "ledger": ledger,
        "open": sum(1 for g in ledger if g.get("status") == "open"),
        "verified": sum(1 for g in ledger if g.get("status") == "verified"),
        "update": latest_update(CONFIG.trace_root),
    }


@mcp.tool(annotations=DESTRUCTIVE)
def fix_with_devin(signature: str = "", session_id: str = "", finding_id: str = "") -> dict:
    """Hand any surfaced issue to Devin AI — it opens a PR with the fix.

    Identify the issue by `signature` (from `bug_ledger()` / a dashboard row) OR by a
    specific `session_id`+`finding_id` (any finding from `get_findings`/`get_run`/a
    replay). Starts a Devin session (capped by devin_max_acu), marks it `fixing`, and
    returns the Devin `devin_url`. Re-run `test_app` after the PR merges and the issue
    auto-verifies. Needs `DEVIN_API_KEY`.
    """
    sig = _resolve_signature(
        {"signature": signature, "session_id": session_id, "finding_id": finding_id}
    )
    return _devin_fix(sig) if sig else {"error": "provide signature or session_id+finding_id"}


@mcp.tool(annotations=EXTERNAL)
def devin_status(devin_session_id: str) -> dict:
    """Poll a Devin fix session; if it opened a PR, record `pr_url` on the issue."""
    return _devin_poll(devin_session_id)


def _stop_and_replay(session_id: str) -> dict:
    """Persist the session, release the billed sandbox, then render the replay."""
    out: dict = {"ok": True}
    session = MANAGER.sessions.get(session_id)
    trace_dir = session.trace.dir if session is not None else None
    if session is not None:
        try:
            session.trace.save_session(session.record)
        except Exception:
            log.warning("save_session failed for %s", session_id, exc_info=True)

    MANAGER.stop(session_id)  # release the billed sandbox BEFORE rendering the replay

    if trace_dir:
        try:
            from .replay import write_replay_html, write_replay_video

            write_replay_video(trace_dir)
            out["replay"] = write_replay_html(trace_dir)
        except Exception:
            log.warning("replay render failed for %s", session_id, exc_info=True)

    # rebuild + serve the dashboard and hand back a clickable localhost link to this run
    out.update(_dashboard_links(session_id))
    return out


@mcp.tool(annotations=DESTRUCTIVE)
def stop(session_id: str) -> StopResult:
    """Tear down the sandbox (released first), then write the replay (html + video)."""
    # resolve an alias to its id so `stop("checkout-flow")` works too
    try:
        session_id = MANAGER.get(session_id).record.id
    except KeyError:
        pass
    return _stop_and_replay(session_id)


def _test_app_sync(repo_path, goal, surface, dev_command, max_steps, alias) -> dict:
    """The blocking autopilot body (launch → explore → teardown + replay + dashboard)."""
    from .autopilot import collect_findings, run_autopilot
    from .driver import get_driver

    surf = Surface(surface) if surface else None
    session = MANAGER.create(repo_path, surf, goal, alias=alias)
    sid = session.record.id

    try:
        ready = session.launch(dev_command)
    except Exception as exc:
        result = _stop_and_replay(sid)
        return {
            "session_id": sid, "alias": session.record.alias,
            "surface": session.record.surface.value,
            "ready": False, "error": str(exc)[:300],
            "findings": [], "findings_total": 0, **result,
        }

    if not ready:
        # launch came up not-ready; still surface any deterministic findings + replay.
        findings = collect_findings(session)
        result = _stop_and_replay(sid)
        return {
            "session_id": sid, "alias": session.record.alias,
            "surface": session.record.surface.value,
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
            "session_id": sid, "alias": session.record.alias,
            "surface": session.record.surface.value,
            "ready": True, "error": str(exc)[:300],
            "findings": findings, "findings_total": len(findings), **result,
        }

    result = _stop_and_replay(sid)  # teardown + replay AFTER the loop finishes
    return {
        "session_id": sid, "alias": session.record.alias,
        "surface": session.record.surface.value,
        "ready": True, **report, **result,
    }


@mcp.tool(annotations=DESTRUCTIVE)
async def test_app(
    repo_path: str,
    goal: str = "exercise the main user flows and find bugs",
    surface: str | None = None,
    dev_command: str | None = None,
    max_steps: int | None = None,
    alias: str | None = None,
    ctx: Context = None,
) -> TestAppResult:
    """ONE CALL: launch the app in a VM, autonomously explore it, and return the bugs found.

    This is the hands-free entry point — it does internally what the granular
    tools do step-by-step. It boots the app in a sandbox, then loops
    observe → (embedded driver model picks the next action) → act, judging each
    step for crashes/console errors/broken behavior, until the driver decides it's
    seen enough or a LoopGuard tripwire (max steps / wall-clock / no-progress)
    fires. Always tears the sandbox down and writes a replay. Never auto-fixes —
    it reports reproducible findings for review.

    Progress is streamed during the (slow) run, and on completion the result carries
    a clickable `dashboard_url` plus a desktop notification — so you can walk away.
    Pass `alias` to give the run a human name in the dashboard/links.
    """
    await _say(ctx, f"Testing {repo_path} — launching the app + autonomously exploring…", 5)
    result = await _run_with_heartbeat(
        ctx, "Testing",
        lambda: _test_app_sync(repo_path, goal, surface, dev_command, max_steps, alias),
    )
    await _say(ctx, result.get("view") or "test session complete", 100)

    # desktop ping with the link — nobody's watching the chat on a long autonomous run
    from .notify import notify
    notify(
        "Inspector — test complete",
        f"{result.get('findings_total', '?')} findings · {result.get('dashboard_url', '')}",
        CONFIG.notify,
    )
    return result


@mcp.tool(annotations=DESTRUCTIVE)
async def test_app_parallel(
    repo_path: str,
    goal: str = "find bugs",
    surface: str | None = None,
    max_agents: int = 4,
    max_steps: int = 5,
    ctx: Context = None,
) -> dict:
    """PLAN → DISPATCH → MERGE: a planner maps the app into parts, then a headless agent
    per part traverses it IN PARALLEL to find bugs, and the findings are merged.

    One scout session looks at the app and decomposes it into its distinct screens/
    features/flows; up to `max_agents` autonomous agents then test those parts at once
    (each its own app instance), so a many-screen app is covered concurrently instead of
    one long serial crawl. Returns the plan, per-agent results, and the merged bug list.
    """
    from .parallel import planned_verify

    surf = Surface(surface) if surface else None
    await _say(ctx, f"Planning {repo_path} → fanning out up to {max_agents} agents…", 5)
    result = await _run_with_heartbeat(
        ctx, "Planning + parallel testing",
        lambda: planned_verify(CONFIG, repo_path, surf, goal, max_steps, max_agents),
    )
    result.update(_dashboard_links())
    await _say(ctx, f"{result.get('total_unique_findings', 0)} unique findings across "
                    f"{result.get('agents', 0)} agents", 100)
    return result


def _test_feature_sync(repo_path, feature, surface, dev_command, alias, max_regions) -> dict:
    """Cartographer body: region-decomposed deterministic lens sweep (docs/15)."""
    from .autopilot import collect_findings
    from .cartographer import run_regions

    surf = Surface(surface) if surface else None
    goal = f"inspect feature: {feature}" if feature else "inspect for bugs (cartographer)"
    session = MANAGER.create(repo_path, surf, goal, alias=alias)
    sid = session.record.id
    try:
        ready = session.launch(dev_command)
    except Exception as exc:
        return {"session_id": sid, "surface": session.record.surface.value, "ready": False,
                "error": str(exc)[:300], "fixes": [], "findings": [], **_stop_and_replay(sid)}
    if not ready:
        return {"session_id": sid, "surface": session.record.surface.value, "ready": False,
                "error": "app never became interactive", "fixes": [], "findings": [], **_stop_and_replay(sid)}
    try:
        report = run_regions(session, max_regions=max_regions)
    except Exception as exc:
        return {"session_id": sid, "surface": session.record.surface.value, "ready": True,
                "error": str(exc)[:300], "fixes": [], "findings": collect_findings(session), **_stop_and_replay(sid)}
    findings = collect_findings(session)  # same shape test_app returns → scoreable in eval
    return {"session_id": sid, "surface": session.record.surface.value, "ready": True,
            "feature": feature, "findings": findings, "findings_total": len(findings),
            **report, **_stop_and_replay(sid)}


@mcp.tool(annotations=DESTRUCTIVE)
async def test_feature(
    repo_path: str,
    feature: str | None = None,
    surface: str | None = None,
    dev_command: str | None = None,
    alias: str | None = None,
    max_regions: int = 8,
    ctx: Context = None,
) -> dict:
    """Cartographer — region-decomposed DETERMINISTIC bug sweep: "I built X, hand me fixes".

    Maps the running UI into regions and runs per-region scripted lens oracles
    (LOGIC_ARITHMETIC + STATE_SYNC in Phase 0) that measure the app's OWN rendered
    state — no LLM in the action choice, no payloads typed — and returns a RANKED FIX
    LIST, each item carrying before/after evidence + a suggested fix. Catches the silent
    logic/state bugs the exploratory `test_app` misses, with no self-inflicted false
    positives. Always tears the app down and writes a replay. Pass `feature` as a label
    for the run (diff-aware scoping is a later phase — see docs/15).
    """
    await _say(ctx, f"Cartographer — inspecting {repo_path}…", 5)
    result = await _run_with_heartbeat(
        ctx, "Inspecting",
        lambda: _test_feature_sync(repo_path, feature, surface, dev_command, alias, max_regions),
    )
    await _say(ctx, f"{result.get('confirmed', 0)} fixes found", 100)
    return result


# --- agentic test-plan orchestration ---

@mcp.tool(annotations=WRITE)
@_friendly
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


@mcp.tool(annotations=WRITE)
@_friendly
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


@mcp.tool(annotations=WRITE)
@_friendly
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
        **_dashboard_links(session_id),  # clickable localhost link to this run's replay
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
   c. After the key action, `check(expectation=...)` and `get_findings(...)`. For web/Electron, call `audit_dom()` to collect deterministic a11y / broken-image / unlabeled-input findings the screenshot can't show.
   d. `update_scenario(scenario_id, status=passed|failed|..., notes=..., finding_ids=[...])`.
   e. If you discover new features mid-run, call `set_plan` again to ADAPT the plan.
5. When no PENDING scenarios remain, `report_issue(...)` anything you SAW that the log tap missed, then `test_report()` and summarize: what passed/failed, the findings (with file:line where available), and recommended fixes. **Finish by giving the user the `dashboard_url` from the result as a clickable link** so they can replay the run and inspect every bug the agent surfaced.

ADVERSARIAL MOVES TO TRY (consult per element type):
{catalog_text()}

Plan first, then execute scenario-by-scenario, deciding the next step each time from what you actually observe. Be thorough, but stop once the plan is covered. Never auto-fix-and-merge — report findings for review."""


# --- MCP resources: past runs as first-class, readable context ---

def _report_markdown(detail: dict) -> str:
    """A compact markdown report the host can attach into a fix conversation."""
    sess = detail.get("session") or {}
    findings = detail.get("findings") or []
    lines = [
        f"# Inspector report — {sess.get('alias') or sess.get('id', '')}",
        f"- surface: {sess.get('surface', '')}",
        f"- goal: {sess.get('goal', '')}",
        f"- repo: {sess.get('repo_path', '')}",
        f"- findings: {len(findings)}",
        "",
        "## Findings",
    ]
    if not findings:
        lines.append("_none_")
    for f in findings:
        lines.append(
            f"- **[{f.get('severity', '?')}]** {f.get('summary', '')}"
            + (f"  ({f.get('suspected_area')})" if f.get("suspected_area") else "")
        )
        if f.get("expected") or f.get("actual"):
            lines.append(f"    - expected: {f.get('expected', '')} · actual: {f.get('actual', '')}")
    return "\n".join(lines)


@mcp.resource("inspector://sessions")
def res_sessions() -> str:
    """All past Inspector runs (summaries + cross-run stats), as JSON."""
    from .dashboard.aggregate import aggregate_stats, scan_sessions

    summaries = scan_sessions(CONFIG.trace_root)
    return json.dumps({"stats": aggregate_stats(summaries), "sessions": summaries}, indent=2)


@mcp.resource("inspector://sessions/{sid}/report")
def res_report(sid: str) -> str:
    """A readable markdown report for one run — pull straight into a fix chat."""
    from .dashboard.aggregate import load_session_detail

    detail = load_session_detail(CONFIG.trace_root, sid)
    if not detail.get("session"):
        return f"# Unknown session {sid!r}"
    return _report_markdown(detail)


@mcp.resource("inspector://sessions/{sid}/findings")
def res_findings(sid: str) -> str:
    """The findings for one run (with fix prompts), as JSON."""
    from .dashboard.aggregate import load_session_detail

    return json.dumps(load_session_detail(CONFIG.trace_root, sid).get("findings", []), indent=2)


def main(argv: list[str] | None = None) -> None:
    """Run the MCP server. Defaults to stdio (Claude Code/Cursor); `--http` exposes it
    over the network so a remote MCP client (e.g. Devin) can connect.

        inspector-mcp serve                        # stdio (also: python -m inspector.server)
        inspector-mcp serve --http                 # http://127.0.0.1:8765/mcp
        inspector-mcp serve --http --port 8765     # loopback only (no auth yet)
    """
    import argparse

    parser = argparse.ArgumentParser(prog="inspector.server")
    parser.add_argument("--transport", choices=["stdio", "http", "sse", "streamable-http"],
                        default=None)
    parser.add_argument("--http", action="store_true", help="shorthand for --transport http")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--path", default=None)
    args, _ = parser.parse_known_args(argv)

    transport = args.transport or ("http" if args.http else CONFIG.transport)
    if transport == "stdio":
        _apply_profile()
        mcp.run()
        return

    host = args.host or CONFIG.http_host
    port = args.port or CONFIG.http_port
    path = args.path or CONFIG.http_path
    # Security triage: Inspector has no HTTP auth yet, so a non-loopback bind would
    # expose full tool access (sandbox spawn, dev_command, arbitrary repo reads) to
    # the network. Refuse it until authentication lands (roadmap Phase 2B).
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"Refusing to bind {transport} on non-loopback host {host!r} without "
            "authentication. Bind 127.0.0.1 and front it with an authenticated "
            "tunnel/proxy, or set INSPECTOR_HTTP_HOST=127.0.0.1."
        )
    _apply_profile()
    log.info("Inspector MCP on %s http://%s:%s%s", transport, host, port, path)
    mcp.run(transport=transport, host=host, port=port, path=path)


if __name__ == "__main__":
    main()
