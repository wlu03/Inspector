"""Tests for the planner (app → parts) + planned_verify wiring, and the plan tools."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import inspector.parallel as P
import inspector.server as server
from inspector.config import Config
from inspector.driver import HeuristicDriver, build_plan_prompt, parse_plan
from inspector.models import Element, SessionRecord, Surface
from inspector.plan import ScenarioStatus, load_plan
from inspector.trace import TraceRecorder


def _el(label, role="button"):
    return Element(id=0, label=label, role=role, bbox=[0, 0, 0.1, 0.1], interactivity=True)


# --- plan prompt + parser (pure) ---

def test_plan_prompt_mentions_elements():
    p = build_plan_prompt([_el("Settings", "tab"), _el("Profile", "tab")], "find bugs")
    assert "Settings" in p and "parts" in p and "JSON" in p


def test_parse_plan():
    parts = parse_plan('{"parts":[{"name":"Settings","goal":"test settings"},'
                       '{"name":"settings","goal":"dup"},{"name":"Profile"}]}')
    assert [p["name"] for p in parts] == ["Settings", "Profile"]   # dedup by name
    assert parts[1]["goal"] == "Profile"                            # goal falls back to name


def test_parse_plan_garbage_is_empty():
    assert parse_plan("not json") == []


# --- heuristic planner: nav elements → parts, else whole app ---

def test_heuristic_plan_from_nav():
    parts = HeuristicDriver().plan(b"", [_el("Settings", "tab"), _el("Profile", "link"),
                                         _el("Save", "button")], "find bugs")
    assert {p["name"] for p in parts} == {"Settings", "Profile"}   # the button is not a part


def test_heuristic_plan_falls_back_to_whole_app():
    parts = HeuristicDriver().plan(b"", [_el("Save", "button")], "find bugs")
    assert parts == [{"name": "app", "goal": "find bugs"}]


# --- planned_verify: plan then dispatch (mocked) ---

def test_planned_verify_plans_then_dispatches(monkeypatch):
    monkeypatch.setattr(P, "plan_parts",
                        lambda cfg, repo, surface, goal: [{"name": "a", "goal": "g"},
                                                          {"name": "b", "goal": "g"}])
    monkeypatch.setattr(P, "parallel_verify",
                        lambda cfg, repo, parts, surface, steps, max_workers: {
                            "parts": [{"part": p["name"]} for p in parts],
                            "agents": len(parts), "merged_findings": [], "total_unique_findings": 0})
    res = P.planned_verify(Config(), "/repo", max_agents=4)
    assert res["agents"] == 2
    assert [p["name"] for p in res["plan"]] == ["a", "b"]


# --- the plan tools: set_plan persists, and a saved plan is re-runnable ---

class _PlanSession:
    """Only what the plan tools touch on a live Session, with a real on-disk trace."""

    def __init__(self, trace_root: str, repo_path: str):
        self.record = SessionRecord(repo_path=repo_path, surface=Surface.WEB)
        self.trace = TraceRecorder(trace_root, self.record.id)
        self.plan = None

    def touch(self) -> None:
        pass


@pytest.fixture
def plan_session(tmp_path, monkeypatch):
    """A registered fake session whose CONFIG points at a throwaway trace root."""
    repo = tmp_path / "app"
    repo.mkdir()
    traces = str(tmp_path / "traces")
    monkeypatch.setattr(server.CONFIG, "trace_root", traces)
    monkeypatch.setattr(server, "_dashboard_links", lambda session_id=None: {})
    session = _PlanSession(traces, str(repo))
    server.MANAGER.sessions[session.record.id] = session
    yield session
    server.MANAGER.sessions.pop(session.record.id, None)


def _scenarios():
    return [{"title": "Checkout", "steps": ['click "Save"'],
             "assertions": [{"kind": "text", "target": "Saved"}]}]


def test_set_plan_saves_a_re_runnable_plan(plan_session):
    out = server.set_plan(plan_session.record.id, "checkout suite", _scenarios())
    assert out["saved"] is True and "save_error" not in out

    listed = server.list_plans(plan_session.record.repo_path)
    assert [p["plan_id"] for p in listed["plans"]] == [out["plan_id"]]
    assert listed["plans"][0]["scenario_count"] == 1

    detail = server.get_plan(out["plan_id"])           # findable by id alone
    assert detail["goal"] == "checkout suite"
    assert detail["scenarios"][0]["assertions"][0]["target"] == "Saved"


def test_get_plan_and_run_plan_report_an_unknown_id(plan_session):
    assert "error" in server.get_plan("plan_missing")
    out = asyncio.run(server.run_plan(plan_session.record.repo_path, "plan_missing"))
    assert out["status"] == "not_run" and "no saved plan" in out["error"]


def test_update_scenario_accumulates_history_in_the_saved_plan(plan_session):
    out = server.set_plan(plan_session.record.id, "g", _scenarios())
    sid = out["scenarios"][0]["id"]
    server.update_scenario(plan_session.record.id, sid, "passed", notes="fine")

    saved = load_plan(server.CONFIG.trace_root, plan_session.record.repo_path,
                      out["plan_id"])
    assert saved.scenarios[0].status == ScenarioStatus.PASSED
    assert [r.session_id for r in saved.scenarios[0].history] == [plan_session.record.id]


def test_adapting_the_plan_mid_run_keeps_the_same_suite(plan_session):
    first = server.set_plan(plan_session.record.id, "g", _scenarios())
    sid = first["scenarios"][0]["id"]
    server.update_scenario(plan_session.record.id, sid, "passed")

    second = server.set_plan(plan_session.record.id, "g",
                             _scenarios() + [{"title": "New idea", "steps": []}])
    assert second["plan_id"] == first["plan_id"]        # one suite, not two
    saved = load_plan(server.CONFIG.trace_root, plan_session.record.repo_path,
                      first["plan_id"])
    assert [s.title for s in saved.scenarios] == ["Checkout", "New idea"]
    assert saved.scenarios[0].history                    # the earlier verdict survived
    assert saved.scenarios[1].history == []


def test_run_plan_tool_walks_the_saved_suite(plan_session, monkeypatch):
    out = server.set_plan(plan_session.record.id, "g", _scenarios())

    class _App:
        record = SimpleNamespace(id="ses_rerun", findings=[],
                                 surface=SimpleNamespace(value="web"))
        last_elements = [Element(id=0, label="Save", bbox=[0, 0, 1, 1])]
        acts: list = []

        def launch(self, dev_command=None):
            return True

        def observe(self):
            return b"", self.last_elements, []

        def act(self, at, target_id=None, text=None, key=None, coords=None, url=""):
            self.acts.append(at.value)

        def observation_context(self, labels=frozenset()):
            return {"texts": ["Saved"], "elements": [], "url": None, "states": {}}

    app = _App()
    monkeypatch.setattr("inspector.session.SessionManager",
                        lambda config: SimpleNamespace(create=lambda *a, **k: app,
                                                       stop=lambda s: None))

    async def _direct(ctx, label, fn):
        return fn()

    monkeypatch.setattr(server, "_run_with_heartbeat", _direct)
    result = asyncio.run(server.run_plan(plan_session.record.repo_path, out["plan_id"]))
    assert result["status"] == "ran" and result["totals"] == {"passed": 1}
    assert app.acts == ["click"]


def test_list_plans_refuses_a_repo_outside_the_workspace_roots(plan_session, monkeypatch):
    monkeypatch.setattr(server.CONFIG, "workspace_roots", ["/nowhere/allowed"])
    out = server.list_plans(plan_session.record.repo_path)
    assert "INSPECTOR_WORKSPACE_ROOTS" in out["error"]
