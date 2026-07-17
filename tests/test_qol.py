"""QoL batch: tool annotations, friendly errors, resources, aliases, notify, auto-refresh."""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

import inspector.server as server
from inspector import notify
from inspector.config import Config
from inspector.dashboard.aggregate import scan_sessions
from inspector.dashboard.render import render_index
from inspector.session import SessionManager


# --- 1. tool annotations (auto-approve safe, prompt on billed) ---------------

def _tool(name):
    return asyncio.run(server.mcp.get_tool(name))


@pytest.mark.parametrize("name", ["observe", "get_findings", "list_runs", "get_run",
                                  "fix_finding", "bug_ledger", "launch_status"])
def test_safe_tools_are_read_only(name):
    assert _tool(name).annotations.readOnlyHint is True


@pytest.mark.parametrize("name", ["test_app", "launch_app", "stop"])
def test_billed_tools_are_destructive(name):
    ann = _tool(name).annotations
    assert ann.destructiveHint is True and ann.readOnlyHint is False


@pytest.mark.parametrize("name", ["act", "report_issue", "set_plan", "update_scenario",
                                  "verify", "audit_dom", "open_dashboard",
                                  "build_dashboard", "test_report", "devin_status"])
def test_mutating_tools_are_write_not_destructive(name):
    ann = _tool(name).annotations
    assert ann.readOnlyHint is False and ann.destructiveHint is False


@pytest.mark.parametrize("name", ["devin_status", "fix_with_devin"])
def test_external_tools_are_openworld(name):
    assert _tool(name).annotations.openWorldHint is True


def test_server_exposes_usage_instructions():
    text = (server.mcp.instructions or "").lower()
    assert "launch_app" in text and "observe" in text and "act" in text and "stop" in text


def test_profiles_partition_the_tool_registry():
    both = server.CORE_TOOLS | server.ADVANCED_TOOLS
    assert not (server.CORE_TOOLS & server.ADVANCED_TOOLS)
    assert len(server.CORE_TOOLS) == 10 and len(both) == 25
    for name in both:  # every classified tool is actually registered
        assert asyncio.run(server.mcp.get_tool(name)) is not None


def test_default_profile_is_core(monkeypatch):
    monkeypatch.delenv("INSPECTOR_PROFILE", raising=False)
    assert Config.from_env().profile == "core"


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
