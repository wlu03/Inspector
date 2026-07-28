"""QoL batch: tool annotations, friendly errors, resources, aliases, notify, auto-refresh."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from types import SimpleNamespace

import pytest

import inspector.server as server
from inspector import notify
from inspector.adapters.base import InputAction, SurfaceAdapter, UnsupportedAction
from inspector.assertions import Assertion, AssertionKind
from inspector.adapters.local_electron import LocalElectronAdapter
from inspector.config import Config
from inspector.dashboard.aggregate import scan_sessions
from inspector.dashboard.render import render_index
from inspector.models import ActionType, Element, SessionRecord, Surface
from inspector.session import Session, SessionManager, summarize_network
from inspector.trace import TraceRecorder


# --- 1. tool annotations (auto-approve safe, prompt on billed) ---------------

def _tool(name):
    return asyncio.run(server.mcp.get_tool(name))


@pytest.mark.parametrize("name", ["observe", "get_findings", "list_runs", "get_run",
                                  "fix_finding", "bug_ledger", "launch_status"])
def test_safe_tools_are_read_only(name):
    assert _tool(name).annotations.readOnlyHint is True


@pytest.mark.parametrize("name", ["test_app", "launch_app", "stop", "verify_fix"])
def test_billed_tools_are_destructive(name):
    ann = _tool(name).annotations
    assert ann.destructiveHint is True and ann.readOnlyHint is False


@pytest.mark.parametrize("name", ["act", "report_issue", "set_plan", "update_scenario",
                                  "check", "audit_dom", "open_dashboard",
                                  "build_dashboard", "test_report", "devin_status",
                                  "update_finding_status"])
def test_mutating_tools_are_write_not_destructive(name):
    ann = _tool(name).annotations
    assert ann.readOnlyHint is False and ann.destructiveHint is False


@pytest.mark.parametrize("name", ["devin_status", "fix_with_devin"])
def test_external_tools_are_openworld(name):
    assert _tool(name).annotations.openWorldHint is True


def test_server_exposes_usage_instructions():
    text = (server.mcp.instructions or "").lower()
    assert "launch_app" in text and "observe" in text and "act" in text and "stop" in text


def test_instructions_document_the_fix_loop_that_core_actually_exposes():
    text = server.mcp.instructions or ""
    # the loop the README headlines has to be reachable under the default profile
    for name in ("update_finding_status", "verify_fix", "report_issue", "check_assertions"):
        assert name in text and name in server.CORE_TOOLS
    # and anything it points at as full-profile-only really is
    for name in ("fix_finding", "bug_ledger", "open_dashboard", "list_runs"):
        assert name in text and name in server.ADVANCED_TOOLS
    # the quoted counts must not drift from the registry
    assert f"exposes {len(server.CORE_TOOLS)} tools" in text
    assert f"adds the other {len(server.ADVANCED_TOOLS)}:" in text


def test_profiles_partition_the_tool_registry():
    both = server.CORE_TOOLS | server.ADVANCED_TOOLS
    assert not (server.CORE_TOOLS & server.ADVANCED_TOOLS)
    assert len(server.CORE_TOOLS) == 16 and len(both) == 32
    for name in both:  # every classified tool is actually registered
        assert asyncio.run(server.mcp.get_tool(name)) is not None


def test_default_profile_is_core(monkeypatch):
    monkeypatch.delenv("INSPECTOR_PROFILE", raising=False)
    assert Config.from_env().profile == "core"


@pytest.mark.parametrize("name", sorted(server.CORE_TOOLS))
def test_core_tools_expose_output_schema(name):
    assert _tool(name).output_schema


# --- 2. friendly error at the boundary ---------------------------------------

def test_friendly_turns_keyerror_into_usable_dict():
    @server._friendly
    def boom(session_id):
        raise KeyError(f"no session {session_id!r}")

    out = boom("ses_missing")
    assert out["error"] == "unknown or expired session"
    assert "active_sessions" in out and "hint" in out


def test_friendly_reraises_unexpected_as_toolerror():
    from fastmcp.exceptions import ToolError

    @server._friendly
    def boom(session_id):
        raise RuntimeError("cdp transport died")

    with pytest.raises(ToolError):
        boom("ses_x")


# --- 10. human session aliases ------------------------------------------------

def test_manager_get_resolves_alias_or_id():
    mgr = SessionManager(Config())
    fake = SimpleNamespace(record=SimpleNamespace(alias="checkout-flow", id="ses_1"),
                           touch=lambda: None)
    mgr.sessions["ses_1"] = fake
    assert mgr.get("ses_1") is fake          # by id
    assert mgr.get("checkout-flow") is fake  # by alias
    with pytest.raises(KeyError):
        mgr.get("nope")


def test_alias_flows_into_dashboard_summary(tmp_path):
    sdir = os.path.join(str(tmp_path), "ses_a")
    os.makedirs(os.path.join(sdir, "findings"))
    with open(os.path.join(sdir, "session.json"), "w") as f:
        json.dump({"id": "ses_a", "alias": "checkout-flow", "surface": "web",
                   "goal": "g", "state": "torn_down", "repo_path": "/r",
                   "created_at": "2026-06-01T00:00:00"}, f)
    [summary] = scan_sessions(str(tmp_path))
    assert summary["alias"] == "checkout-flow"


# --- 11. desktop notification (command building is pure + testable) ----------

def test_notify_command_macos(monkeypatch):
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    cmd = notify.notify_command("Inspector", "done · http://x")
    assert cmd[0] == "osascript" and "display notification" in cmd[2]


def test_notify_command_linux_needs_notify_send(monkeypatch):
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notify.shutil, "which", lambda b: "/usr/bin/notify-send")
    assert notify.notify_command("t", "m")[0] == "notify-send"


def test_notify_command_unsupported_is_none(monkeypatch):
    monkeypatch.setattr(notify.platform, "system", lambda: "Plan9")
    assert notify.notify_command("t", "m") is None


def test_notify_disabled_is_a_noop():
    assert notify.notify("t", "m", enabled=False) is False


# --- 5. MCP resources --------------------------------------------------------

def test_resources_registered_and_read_the_trace(tmp_path, monkeypatch):
    sdir = os.path.join(str(tmp_path), "ses_a")
    os.makedirs(os.path.join(sdir, "findings"))
    with open(os.path.join(sdir, "session.json"), "w") as f:
        json.dump({"id": "ses_a", "alias": "checkout", "surface": "web", "goal": "g",
                   "state": "torn_down", "repo_path": "/r",
                   "created_at": "2026-06-01T00:00:00"}, f)
    with open(os.path.join(sdir, "findings", "f1.json"), "w") as f:
        json.dump({"id": "f1", "summary": "boom", "severity": "high", "status": "open"}, f)
    monkeypatch.setattr(server.CONFIG, "trace_root", str(tmp_path))

    assert asyncio.run(server.mcp.get_resource("inspector://sessions")) is not None  # plain one registered
    payload = json.loads(server.res_sessions())
    assert any(s["id"] == "ses_a" for s in payload["sessions"])
    assert "Inspector report" in server.res_report("ses_a")
    assert json.loads(server.res_findings("ses_a"))[0]["id"] == "f1"


def test_report_markdown_renders_findings():
    detail = {
        "session": {"id": "ses_a", "alias": "checkout", "surface": "web", "goal": "g",
                    "repo_path": "/r"},
        "findings": [{"severity": "high", "summary": "Save does nothing",
                      "suspected_area": "App.jsx:10", "expected": "toast", "actual": "none"}],
    }
    md = server._report_markdown(detail)
    assert "# Inspector report — checkout" in md
    assert "Save does nothing" in md and "App.jsx:10" in md


# --- 12. dashboard auto-refresh + alias display ------------------------------

def test_dashboard_has_autorefresh_and_alias():
    summaries = [{
        "id": "ses_a", "alias": "checkout-flow", "surface": "web", "goal": "g",
        "state": "torn_down", "passed": None, "by_severity": {}, "n_actions": 3,
        "n_frames": 7, "created_at": "2026-06-01T00:00:00", "replay_path": "ses_a/index.html",
        "repo_path": "/r",
    }]
    stats = {"n_sessions": 1, "findings_total": 0, "by_severity": {}, "pass_rate": None}
    html = render_index(summaries, stats, [])
    assert "new runs available" in html and "pollNew" in html       # auto-refresh
    assert "__INSP_COUNT__=1" in html                                # current count embedded
    assert "checkout-flow" in html                                   # alias shown on the row


def test_dashboard_has_live_feed_and_ticking_times():
    stats = {"n_sessions": 0, "findings_total": 0, "by_severity": {}, "pass_rate": None}
    html = render_index([], stats, [])
    assert "id='live'" in html and "Running now" in html             # live panel
    assert "pollLive" in html and "live.json" in html and "RUNNING" in html
    assert "function ago(" in html and "tickTimes" in html           # ticking relative time


# --- 13. the action schema: every parameter really reaches the adapter -------

class _StubAdapter(SurfaceAdapter):
    """A surface that records what it was asked to do. `can` is what it admits to
    supporting, so the "this surface cannot" path is testable without a phone."""

    surface = Surface.WEB

    def __init__(self, can=()):
        self.actions = []
        self.calls = []
        self.can = set(can)

    def screen_size(self):
        return (1000, 1000)

    def input(self, action):
        self.actions.append(action)

    def navigate(self, url):
        self.calls.append(("navigate", url))
        return "navigate" in self.can

    def go_back(self):
        self.calls.append(("go_back",))
        return "go_back" in self.can

    def go_forward(self):
        self.calls.append(("go_forward",))
        return "go_forward" in self.can

    def reload(self):
        self.calls.append(("reload",))
        return "reload" in self.can

    def launch(self, repo_path, dev_command=None): pass
    def is_ready(self): return True
    def screenshot(self): return b""
    def logs(self): return []
    def teardown(self): pass


def _bare_session(*elements, can=()) -> Session:
    """A Session with nothing but the state the action resolver reads — building a real
    one would boot a sandbox, a detector and a trace recorder."""
    s = Session.__new__(Session)
    s.adapter = _StubAdapter(can)
    s.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)
    s.last_elements = list(elements)
    s.action_log = []
    return s


def _el(el_id: int, x: float, y: float, label: str = "") -> Element:
    return Element(id=el_id, label=label, bbox=[x, y, x, y], interactivity=True)


def test_drag_resolves_a_destination_instead_of_refusing():
    s = _bare_session(_el(0, 0.1, 0.1, "Card"), _el(1, 0.8, 0.8, "Done"))
    action = s._resolve(ActionType.DRAG, 0, None, None, None, to_id=1)
    assert (action.x, action.y) == (100, 100)
    assert (action.to_x, action.to_y) == (800, 800)


def test_drag_destination_can_be_raw_coordinates():
    s = _bare_session(_el(0, 0.1, 0.1, "Card"))
    action = s._resolve(ActionType.DRAG, 0, None, None, None, to_coords=[640, 480])
    assert (action.to_x, action.to_y) == (640, 480)


def test_drag_without_a_destination_is_refused_not_silently_a_click():
    s = _bare_session(_el(0, 0.1, 0.1, "Card"))
    with pytest.raises(ValueError, match="to_id or to_coords"):
        s._resolve(ActionType.DRAG, 0, None, None, None)


def test_scroll_direction_and_amount_reach_the_input_action():
    s = _bare_session()
    action = s._resolve(ActionType.SCROLL, None, None, None, None, direction="up", amount=9)
    assert action.direction == "up" and action.amount == 9
    # the default is the historical one, so existing callers scroll exactly as before
    default = s._resolve(ActionType.SCROLL, None, None, None, None)
    assert default.direction == "down" and default.amount == 3


def test_unknown_scroll_direction_is_refused_rather_than_scrolling_down():
    s = _bare_session()
    with pytest.raises(ValueError, match="scroll direction"):
        s._resolve(ActionType.SCROLL, None, None, None, None, direction="downward")


def test_scroll_amount_never_collapses_to_a_no_op():
    s = _bare_session()
    assert s._resolve(ActionType.SCROLL, None, None, None, None, amount=0).amount == 1


class _ScrollCDP:
    def __init__(self):
        self.calls = []

    def scroll(self, x, y, dy):
        self.calls.append((x, y, dy))


def _scroll_adapter():
    a = LocalElectronAdapter(Config())
    a.cdp = _ScrollCDP()
    a._viewport = (1200, 900)
    return a


def test_cdp_scroll_honours_direction_and_amount():
    a = _scroll_adapter()
    a.input(InputAction(ActionType.SCROLL, direction="up", amount=3))
    a.input(InputAction(ActionType.SCROLL, direction="down", amount=9))
    (_x, _y, up), (_x2, _y2, down) = a.cdp.calls
    assert up < 0 < down and abs(down) == 3 * abs(up)
    # amount=3 (the default) is still a third of the viewport, as it always was
    assert abs(up) == 300


# --- 14. navigation and the explicit "this surface cannot" signal ------------

def test_navigate_goes_to_the_adapters_navigation_hook():
    s = _bare_session(can={"navigate"})
    s._dispatch(s._resolve(ActionType.NAVIGATE, None, None, None, None, url="/settings"))
    assert s.adapter.calls == [("navigate", "/settings")]
    assert s.adapter.actions == []  # navigation is NOT an input event


def test_navigate_without_a_url_is_refused():
    s = _bare_session(can={"navigate"})
    with pytest.raises(ValueError, match="url"):
        s._resolve(ActionType.NAVIGATE, None, None, None, None)


def test_a_surface_that_cannot_navigate_says_so_with_a_reason():
    s = _bare_session()  # every capability answers False
    with pytest.raises(UnsupportedAction, match="/settings"):
        s._dispatch(s._resolve(ActionType.NAVIGATE, None, None, None, None, url="/settings"))


@pytest.mark.parametrize("action,hook", [
    (ActionType.BACK, "go_back"),
    (ActionType.FORWARD, "go_forward"),
    (ActionType.RELOAD, "reload"),
])
def test_history_actions_reach_their_hook_and_report_when_they_cannot(action, hook):
    ok = _bare_session(can={hook})
    ok._dispatch(ok._resolve(action, None, None, None, None))
    assert ok.adapter.calls == [(hook,)]
    with pytest.raises(UnsupportedAction, match=ok.record.surface.value):
        _bare_session()._dispatch(_bare_session()._resolve(action, None, None, None, None))


def test_an_input_the_surface_does_not_dispatch_is_reported_not_dropped():
    # the base if/elif chain has no else: without this guard a hover on a surface that
    # can't hover returns quietly and reads exactly like a hover that worked
    s = _bare_session(_el(0, 0.5, 0.5, "Menu"))
    with pytest.raises(UnsupportedAction, match="hover"):
        s._dispatch(s._resolve(ActionType.HOVER, 0, None, None, None))
    assert s.adapter.actions == []


def test_the_cdp_surface_declares_the_pointer_actions_it_really_has():
    a = LocalElectronAdapter(Config())
    assert a.supports_input(ActionType.HOVER) and a.supports_input(ActionType.RIGHT_CLICK)
    assert not SurfaceAdapter.input_actions & {ActionType.HOVER, ActionType.RIGHT_CLICK}


class _PointerCDP:
    def __init__(self):
        self.calls = []

    def hover(self, x, y):
        self.calls.append(("hover", x, y))

    def right_click(self, x, y):
        self.calls.append(("right_click", x, y))


def test_hover_and_right_click_dispatch_real_mouse_events():
    a = LocalElectronAdapter(Config())
    a.cdp = _PointerCDP()
    a.input(InputAction(ActionType.HOVER, x=10, y=20))
    a.input(InputAction(ActionType.RIGHT_CLICK, x=30, y=40))
    assert a.cdp.calls == [("hover", 10, 20), ("right_click", 30, 40)]


def test_a_refused_action_leaves_no_step_in_the_repro_script():
    from inspector.loop import LoopGuard

    s = _bare_session()
    s.guard = LoopGuard()
    s.action_seq = 0
    s._capture_lock = threading.Lock()
    s.trace = SimpleNamespace(save_frame=lambda png: "frame", record_action=lambda a: None)
    with pytest.raises(UnsupportedAction):
        s.act(ActionType.NAVIGATE, url="/settings")
    # the log is the repro script; a navigation that never happened must not appear in it
    assert s.action_log == []
    assert s.action_seq == 1  # but the trace still records the attempt


def test_act_tool_advertises_the_drag_and_scroll_parameters():
    params = asyncio.run(server.mcp.get_tool("act")).parameters["properties"]
    for name in ("to_id", "to_coords", "direction", "amount", "url"):
        assert name in params
    text = asyncio.run(server.mcp.get_tool("act")).description
    assert "drag" in text and "to_id" in text and "direction" in text


def test_act_docstring_lists_exactly_the_action_types_that_exist():
    # the docstring is the calling agent's only reference; a type missing from it is a
    # capability nobody will ever use, and one listed that doesn't exist is a dead turn
    text = asyncio.run(server.mcp.get_tool("act")).description
    listed = re.search(r"`type` is one of:(.*?)\.", text, re.S).group(1)
    assert {w.strip() for w in listed.split(",")} == {t.value for t in ActionType}


def test_act_tool_rejects_an_unknown_type_by_naming_the_valid_ones():
    with pytest.raises(ValueError, match="click"):
        server._action_type("clic")


# --- 15. the network channel: bounded at the boundary, findings for real failures ---

def _rec(url, status=None, failed=False, error="", method="GET") -> dict:
    """One record shaped exactly as CDPClient.drain_network returns them."""
    return {"request_id": url, "method": method, "url": url, "resource_type": "xhr",
            "status": status, "mime_type": "", "failed": failed, "error": error,
            "duration_ms": 12}


def test_network_summary_leads_with_failures_and_counts_the_rest():
    records = [_rec(f"http://x/chunk{i}.js", 200) for i in range(40)]
    records += [_rec("http://x/api/me", 404), _rec("http://x/api/items", 500),
                _rec("http://x/api/save", failed=True, error="net::ERR_CONNECTION_REFUSED")]
    out = summarize_network(records)
    assert out["total"] == 43
    # worst first: the transport failure, then 500, then 404 — the agent reads top-down
    assert [p["url"] for p in out["problems"]] == [
        "http://x/api/save", "http://x/api/items", "http://x/api/me"]
    # the 40 that worked cost four tokens, not forty lines
    assert out["ok"] == {"count": 40, "by_status": {"2xx": 40}}
    assert all(p["status"] != 200 for p in out["problems"])


def test_network_summary_caps_the_problem_list_and_admits_the_truncation():
    out = summarize_network([_rec(f"http://x/api/{i}", 500) for i in range(30)], limit=5)
    assert len(out["problems"]) == 5 and out["problems_omitted"] == 25


def test_a_request_still_in_flight_is_counted_not_called_a_failure():
    out = summarize_network([_rec("http://x/stream")])
    assert out["pending"] == 1 and out["problems"] == [] and out["ok"]["count"] == 0


def _finding_session(tmp_path) -> Session:
    """A Session with only what the deterministic finding path touches."""
    s = Session.__new__(Session)
    s.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)
    s.trace = TraceRecorder(str(tmp_path), s.record.id)
    s.adapter = SimpleNamespace(cdp=None)
    s.action_log = []
    s.last_assertions = []
    s._seen_findings = set()
    return s


def _saved_findings(session) -> list[dict]:
    names = sorted(os.listdir(session.trace.findings_dir))
    out = []
    for name in names:
        with open(os.path.join(session.trace.findings_dir, name)) as f:
            out.append(json.load(f))
    return out


def test_failed_and_5xx_requests_become_findings_with_a_repro_trail(tmp_path):
    s = _finding_session(tmp_path)
    s.action_log = ["click element #2 (Save)"]
    new = s._ingest_findings([], [
        _rec("http://x/api/save", failed=True, error="net::ERR_FAILED", method="post"),
        _rec("http://x/api/items", 500),
        _rec("http://x/api/me", 401),   # normal on an app you haven't logged into
        _rec("http://x/main.js", 200),
    ])
    assert new == 2
    saved = _saved_findings(s)
    assert {f["severity"] for f in saved} == {"high"}
    assert any("POST http://x/api/save failed" in f["summary"] for f in saved)
    assert any("GET http://x/api/items returned 500" in f["summary"] for f in saved)
    # the same treatment console errors get: a repro trail and a replayable spec
    assert all(f["repro"] == ["click element #2 (Save)"] for f in saved)
    assert all(f["repro_spec"]["steps"] for f in saved)


def test_a_polled_broken_endpoint_files_one_finding_not_hundreds(tmp_path):
    s = _finding_session(tmp_path)
    first = s._ingest_findings([], [_rec("http://x/api/items?cursor=1", 500)])
    again = s._ingest_findings([], [_rec("http://x/api/items?cursor=2", 503)])
    assert first == 1 and again == 0


def test_an_aborted_request_is_not_reported_as_a_bug(tmp_path):
    s = _finding_session(tmp_path)
    assert s._ingest_findings(
        [], [_rec("http://x/api/search", failed=True, error="net::ERR_ABORTED")]) == 0


class _NetAdapter(_StubAdapter):
    """A surface that really taps traffic — it overrides the hook, the base stub doesn't."""

    def network(self):
        return []


class _NetSession:
    """Only what the observe tool reads off a live session."""

    def __init__(self, adapter, network):
        self.adapter = adapter
        self.last_network = list(network)
        self.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)

    def observe(self):
        return b"png", [], []

    def image_allowed(self):
        return False

    def touch(self):
        pass


def _observe_with(adapter, network) -> dict:
    server.MANAGER.sessions["ses_net"] = _NetSession(adapter, network)
    try:
        return server.observe("ses_net", include_image=False)
    finally:
        server.MANAGER.sessions.pop("ses_net", None)


def test_observe_returns_the_bounded_network_window():
    out = _observe_with(_NetAdapter(), [_rec("http://x/api/items", 500),
                                        _rec("http://x/main.js", 200)])
    assert out["network"]["problems"][0]["status"] == 500
    assert out["network"]["ok"]["count"] == 1


def test_observe_omits_network_on_a_surface_that_cannot_see_traffic():
    # absent is the honest answer: an empty summary would read as "no requests were made"
    assert "network" not in _observe_with(_StubAdapter(), [])


# --- 16. viewport + captured session state at the MCP boundary ----------------

class _ViewportAdapter(_StubAdapter):
    """A surface that records resize requests and can be told to refuse them."""

    def __init__(self, ok=True):
        super().__init__()
        self.ok = ok
        self.viewports = []

    def set_viewport(self, width, height, mobile=False):
        self.viewports.append((width, height, mobile))
        return self.ok


class _StateAdapter(_StubAdapter):
    """A surface with a real session channel: capture hands back credentials, seed takes
    them. The values are deliberately distinctive so a leak is greppable."""

    STATE = {"origin": "http://app", "cookies": [{"name": "sid", "value": "s3cr3t"}],
             "local_storage": {"token": "t0ken"}, "session_storage": {}}

    def __init__(self):
        super().__init__()
        self.seeded = []

    def capture_state(self):
        return dict(self.STATE)

    def seed_state(self, state):
        self.seeded.append(state)
        return True


def _session_with(adapter) -> Session:
    """A Session carrying only what the viewport/state path touches."""
    s = Session.__new__(Session)
    s.adapter = adapter
    s.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)
    s.last_elements = [_el(0, 0.5, 0.5, "Save")]
    s._capture_lock = threading.Lock()
    return s


def _with_session(session):
    server.MANAGER.sessions[session.record.id] = session
    return session.record.id


def test_set_viewport_drops_element_ids_measured_at_the_old_size():
    s = _session_with(_ViewportAdapter())
    assert s.set_viewport(375, 812, mobile=True) is True
    assert s.adapter.viewports == [(375, 812, True)]
    # a click on #0 now would land at 375px * a fraction of the 1280px screen it was measured on
    assert s.last_elements == []


def test_a_refused_resize_keeps_the_observation_that_is_still_true():
    s = _session_with(_ViewportAdapter(ok=False))
    assert s.set_viewport(375, 812) is False
    assert s.last_elements


def test_set_viewport_tool_reports_a_surface_that_cannot_resize():
    sid = _with_session(_session_with(_ViewportAdapter(ok=False)))
    try:
        out = server.set_viewport(sid, 375, 812)
    finally:
        server.MANAGER.sessions.pop(sid, None)
    assert out["ok"] is False and "could not resize" in out["error"]


def test_set_viewport_tool_refuses_a_degenerate_size():
    sid = _with_session(_session_with(_ViewportAdapter()))
    try:
        out = server.set_viewport(sid, 0, 812)
    finally:
        server.MANAGER.sessions.pop(sid, None)
    assert out["ok"] is False and "positive" in out["error"]


def test_capture_then_seed_replays_a_login_through_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server.CONFIG, "trace_root", str(tmp_path))
    session = _session_with(_StateAdapter())
    sid = _with_session(session)
    try:
        saved = server.capture_state(sid, name="login")
        seeded = server.seed_state(sid, name="login")
    finally:
        server.MANAGER.sessions.pop(sid, None)
    assert saved["ok"] and saved["saved_as"] == "login" and saved["origin"] == "http://app"
    assert saved["cookies"] == 1 and saved["local_storage_keys"] == 1
    assert os.path.exists(os.path.join(str(tmp_path), "state", "login.json"))
    # the state that reaches the adapter is the one that was captured, byte for byte
    assert seeded["ok"] is True and session.adapter.seeded == [_StateAdapter.STATE]


def test_seed_state_says_so_when_there_is_nothing_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(server.CONFIG, "trace_root", str(tmp_path))
    sid = _with_session(_session_with(_StateAdapter()))
    try:
        missing = server.seed_state(sid, name="never-captured")
        empty = server.seed_state(sid, state={})
    finally:
        server.MANAGER.sessions.pop(sid, None)
    # both must be a loud false: a caller told "seeded" reads every logged-out screen
    # that follows as a bug in the app
    assert missing["ok"] is False and "capture_state" in missing["error"]
    assert empty["ok"] is False and "install nothing" in empty["error"]


def test_capture_state_refuses_to_save_an_empty_session(tmp_path, monkeypatch):
    monkeypatch.setattr(server.CONFIG, "trace_root", str(tmp_path))
    sid = _with_session(_session_with(_StubAdapter()))  # no session channel at all
    try:
        out = server.capture_state(sid, name="login")
    finally:
        server.MANAGER.sessions.pop(sid, None)
    assert out["ok"] is False and "nothing to capture" in out["error"]
    assert not os.path.exists(os.path.join(str(tmp_path), "state", "login.json"))


class _ChannelAdapter(_NetAdapter):
    def text_elements(self):
        return [Element(id=9, label="Welcome back", bbox=[0, 0, 1, 1])]

    def control_state(self, element_id):
        return {"value": "Alice"}


class _ChannelSession:
    """Session-shaped enough for the one channel gatherer both paths now use."""

    def __init__(self):
        self.adapter = _ChannelAdapter()
        self.last_network = [_rec("http://x/api/items", 500)]

    def observe(self):
        return b"", [Element(id=0, label="Name", role="textbox", bbox=[0, 0, 1, 1])], []


def test_check_assertions_reads_exactly_what_re_verification_reads():
    # these were two near-identical copies; an oracle judged against a different set of
    # facts at file time than at re-verify time is the one comparison that must not drift
    stub = _ChannelSession()
    from_tool = server._assertion_context(
        stub, [Assertion(kind=AssertionKind.VALUE, on="Name", expected="Alice")])
    from_oracle = Session.observation_context(stub, {"Name"})
    assert from_tool == from_oracle
    assert from_tool["states"]["name"] == {"value": "Alice"}
    assert "Welcome back" in from_tool["texts"]
    # and the new channel arrived in both at once
    assert from_tool["network"] == stub.last_network


def test_a_surface_without_a_tap_reports_no_network_channel_not_an_empty_one():
    stub = _ChannelSession()
    stub.adapter = _StubAdapter()
    assert Session.observation_context(stub, frozenset())["network"] is None


def test_live_sessions_provider_reads_the_manager():
    # the /live.json provider: pull running sessions straight off the manager
    fake = SimpleNamespace(
        record=SimpleNamespace(id="ses_1", alias="checkout", goal="g",
                               surface=SimpleNamespace(value="web"),
                               state=SimpleNamespace(value="interacting"), findings=["a", "b"],
                               created_at="2026-06-21T00:00:00"),
        trace=SimpleNamespace(_frame_n=12),
    )
    server.MANAGER.sessions["ses_1"] = fake
    try:
        live = server._live_sessions()["sessions"]
        row = next(s for s in live if s["id"] == "ses_1")
        assert row["alias"] == "checkout" and row["findings"] == 2 and row["frames"] == 12
        assert row["state"] == "interacting"
    finally:
        server.MANAGER.sessions.pop("ses_1", None)


class _AuditSession:
    """Minimal session whose audit() returns a canned raw audit dict."""

    def __init__(self, audit: dict):
        self._audit = audit
        self.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)

    def audit(self):
        return self._audit, []

    def touch(self):
        pass


def _audit_dom_with(audit: dict) -> dict:
    server.MANAGER.sessions["ses_audit"] = _AuditSession(audit)
    try:
        return server.audit_dom("ses_audit")
    finally:
        server.MANAGER.sessions.pop("ses_audit", None)


def test_audit_dom_forwards_the_axe_failure_reason():
    # an empty violations list must never reach the agent looking like a clean pass
    out = _audit_dom_with({"axe_violations": [], "broken_images": ["/a.png"],
                           "unlabeled_inputs": [], "axe_error": "CSP blocked the injection"})
    assert out["axe_ran"] is False
    assert "CSP" in out["axe_error"]
    # the pure-DOM checks are unaffected by axe failing, so they stay trustworthy
    assert out["broken_images"] == ["/a.png"]


def test_audit_dom_reports_a_real_pass_as_a_real_pass():
    out = _audit_dom_with({"axe_violations": [], "broken_images": [],
                           "unlabeled_inputs": [], "axe_ran": True})
    assert out["axe_ran"] is True
    assert "axe_error" not in out
