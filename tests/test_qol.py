"""QoL batch: tool annotations, friendly errors, resources, aliases, notify, auto-refresh."""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

import inspector.server as server
from inspector import notify
from inspector.adapters.base import InputAction
from inspector.adapters.local_electron import LocalElectronAdapter
from inspector.config import Config
from inspector.dashboard.aggregate import scan_sessions
from inspector.dashboard.render import render_index
from inspector.models import ActionType, Element
from inspector.session import Session, SessionManager


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
    assert len(server.CORE_TOOLS) == 13 and len(both) == 26
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

class _StubAdapter:
    """Only the two methods `Session._resolve` touches, so no app has to be running."""

    def __init__(self):
        self.actions = []

    def screen_size(self):
        return (1000, 1000)

    def input(self, action):
        self.actions.append(action)


def _bare_session(*elements) -> Session:
    """A Session with nothing but the state the action resolver reads — building a real
    one would boot a sandbox, a detector and a trace recorder."""
    s = Session.__new__(Session)
    s.adapter = _StubAdapter()
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


def test_act_tool_advertises_the_drag_and_scroll_parameters():
    params = asyncio.run(server.mcp.get_tool("act")).parameters["properties"]
    for name in ("to_id", "to_coords", "direction", "amount"):
        assert name in params
    text = asyncio.run(server.mcp.get_tool("act")).description
    assert "drag" in text and "to_id" in text and "direction" in text


def test_act_tool_rejects_an_unknown_type_by_naming_the_valid_ones():
    with pytest.raises(ValueError, match="click"):
        server._action_type("clic")


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
