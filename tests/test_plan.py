"""Test plans: the model, the durable per-repo store, and re-running a saved plan."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from inspector.assertions import Assertion, AssertionKind
from inspector.config import Config
from inspector.models import Element
from inspector.plan import (
    ScenarioStatus,
    build_plan,
    find_plan,
    list_plans,
    load_plan,
    parse_step,
    run_plan,
    run_scenario,
    save_plan,
)


def test_build_plan():
    plan = build_plan(
        "ses_x",
        "test the save flow",
        [{"title": "Save flow", "rationale": "core", "steps": ["click save"], "expected": "toast"}],
    )
    assert plan.goal == "test the save flow"
    assert len(plan.scenarios) == 1
    s = plan.scenarios[0]
    assert s.title == "Save flow"
    assert s.steps == ["click save"]
    assert s.status == ScenarioStatus.PENDING
    assert plan.get(s.id) is s
    assert plan.pending() == [s]


def test_build_plan_empty():
    plan = build_plan("ses_y", "nothing", [])
    assert plan.scenarios == []
    assert plan.pending() == []


def test_build_plan_parses_the_scenario_oracle_and_drops_junk():
    plan = build_plan("ses_z", "g", [{"title": "Save", "assertions": [
        {"kind": "text", "target": "Saved"},
        {"kind": "not-a-kind"},          # malformed → dropped, the plan still builds
    ]}])
    [a] = plan.scenarios[0].assertions
    assert a.kind == AssertionKind.TEXT and a.target == "Saved"


# --- cross-run accumulation ---------------------------------------------------

def test_scenario_history_accumulates_and_surfaces_a_regression():
    plan = build_plan("ses_1", "g", [{"title": "Checkout"}])
    s = plan.scenarios[0]
    s.record_run(ScenarioStatus.PASSED, session_id="ses_1", notes="fine")
    s.record_run(ScenarioStatus.FAILED, session_id="ses_2", notes="500 on submit",
                 finding_ids=["fnd_a"])
    assert [r.status for r in s.history] == [ScenarioStatus.PASSED, ScenarioStatus.FAILED]
    assert s.status == ScenarioStatus.FAILED and s.finding_ids == ["fnd_a"]
    assert s.regressed() and plan.regressions() == [s]


def test_recording_twice_in_one_session_is_one_run_not_a_regression():
    plan = build_plan("ses_1", "g", [{"title": "Checkout"}])
    s = plan.scenarios[0]
    s.record_run(ScenarioStatus.PASSED, session_id="ses_1")
    s.record_run(ScenarioStatus.FAILED, session_id="ses_1", finding_ids=["fnd_a"])
    assert len(s.history) == 1 and s.status == ScenarioStatus.FAILED
    assert not s.regressed()          # the same run corrected itself; nothing regressed


def test_finding_ids_accumulate_across_runs():
    plan = build_plan("ses_1", "g", [{"title": "Checkout"}])
    s = plan.scenarios[0]
    s.record_run(ScenarioStatus.FAILED, session_id="ses_1", finding_ids=["fnd_a"])
    s.record_run(ScenarioStatus.FAILED, session_id="ses_2", finding_ids=["fnd_a", "fnd_b"])
    assert s.finding_ids == ["fnd_a", "fnd_b"]
    assert s.history[0].finding_ids == ["fnd_a"]   # each run still knows what IT saw


def test_adopt_history_survives_an_adapted_plan():
    old = build_plan("ses_1", "g", [{"title": "Checkout flow"}, {"title": "Gone"}])
    old.scenarios[0].record_run(ScenarioStatus.PASSED, session_id="ses_1")
    old.runs = ["ses_1"]

    new = build_plan("ses_2", "g", [{"title": "checkout  FLOW"}, {"title": "Brand new"}])
    new.adopt_history(old)
    assert new.scenarios[0].history and new.scenarios[0].status == ScenarioStatus.PASSED
    assert new.scenarios[1].history == []          # a genuinely new scenario starts clean
    assert new.runs == ["ses_1"] and new.created_at == old.created_at


def test_begin_run_resets_status_but_keeps_history():
    plan = build_plan("ses_1", "g", [{"title": "Checkout"}])
    plan.scenarios[0].record_run(ScenarioStatus.PASSED, session_id="ses_1")
    plan.begin_run("ses_2")
    assert plan.runs == ["ses_2"]
    assert plan.scenarios[0].status == ScenarioStatus.PENDING   # nothing is done yet
    assert len(plan.scenarios[0].history) == 1                  # ...but last time is kept


# --- the durable per-repo store ----------------------------------------------

def test_save_and_load_round_trip(tmp_path):
    repo = str(tmp_path / "app")
    os.makedirs(repo)
    plan = build_plan("ses_1", "checkout", [{"title": "Buy", "steps": ['click "Save"']}],
                      repo_path=repo)
    plan.scenarios[0].record_run(ScenarioStatus.PASSED, session_id="ses_1")
    path = save_plan(str(tmp_path / "traces"), plan)

    assert os.path.basename(path) == f"{plan.id}.json"
    assert os.path.basename(os.path.dirname(os.path.dirname(path))) == "plans"
    back = load_plan(str(tmp_path / "traces"), repo, plan.id)
    assert back.goal == "checkout"
    assert back.scenarios[0].history[0].status == ScenarioStatus.PASSED


def test_plans_are_filed_per_repo(tmp_path):
    traces = str(tmp_path / "traces")
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    os.makedirs(a), os.makedirs(b)
    pa = build_plan("ses_1", "a-goal", [], repo_path=a)
    pb = build_plan("ses_2", "b-goal", [], repo_path=b)
    save_plan(traces, pa)
    save_plan(traces, pb)

    assert [p.goal for p in list_plans(traces, a)] == ["a-goal"]
    assert [p.goal for p in list_plans(traces, b)] == ["b-goal"]
    assert load_plan(traces, a, pb.id) is None          # b's plan is not a's to load
    assert find_plan(traces, pb.id).goal == "b-goal"    # ...but findable by id alone


def test_a_traversal_repo_path_lands_in_the_same_canonical_directory(tmp_path):
    traces = str(tmp_path / "traces")
    repo = str(tmp_path / "app")
    os.makedirs(repo)
    plan = build_plan("ses_1", "g", [], repo_path=repo)
    save_plan(traces, plan)
    sneaky = os.path.join(repo, "..", "app")
    assert load_plan(traces, sneaky, plan.id) is not None
    # and nothing escaped the trace root
    assert os.path.isfile(os.path.join(traces, "plans", os.listdir(
        os.path.join(traces, "plans"))[0], f"{plan.id}.json"))


def test_a_repo_outside_the_workspace_roots_is_refused(tmp_path):
    plan = build_plan("ses_1", "g", [], repo_path=str(tmp_path / "elsewhere"))
    with pytest.raises(PermissionError):
        save_plan(str(tmp_path / "traces"), plan, [str(tmp_path / "allowed")])


def test_a_bad_plan_id_is_never_joined_onto_a_path(tmp_path):
    plan = build_plan("ses_1", "g", [], repo_path=str(tmp_path))
    plan.id = "../../etc/passwd"
    with pytest.raises(ValueError):
        save_plan(str(tmp_path / "traces"), plan)
    assert load_plan(str(tmp_path / "traces"), str(tmp_path), "../evil") is None
    assert find_plan(str(tmp_path / "traces"), "../evil") is None


def test_an_unreadable_plan_file_is_skipped_not_raised(tmp_path):
    traces = str(tmp_path / "traces")
    repo = str(tmp_path)
    plan = build_plan("ses_1", "g", [], repo_path=repo)
    path = save_plan(traces, plan)
    with open(os.path.join(os.path.dirname(path), "junk.json"), "w") as f:
        f.write("{not json")
    assert [p.id for p in list_plans(traces, repo)] == [plan.id]


def test_list_plans_on_an_unknown_repo_is_empty(tmp_path):
    assert list_plans(str(tmp_path / "traces"), str(tmp_path / "nope")) == []


# --- step parsing -------------------------------------------------------------

@pytest.mark.parametrize("text,action,field,value", [
    ('click "Save"', "click", "locator", "Save"),
    ("Click the Save button", "click", "locator", "Save"),
    ("double-click the row", "double_click", "locator", "row"),
    ('type "hello" into the name field', "type", "text", "hello"),
    ("type admin@example.com in the email field", "type", "text", "admin@example.com"),
    ('press "Enter"', "key", "key", "Enter"),
    ('navigate to "/cart"', "navigate", "url", "/cart"),
    ("go to /settings", "navigate", "url", "/settings"),
])
def test_parse_step(text, action, field, value):
    step = parse_step(text)
    assert step.action == action and getattr(step, field) == value


def test_parse_step_bare_and_unparseable():
    assert parse_step("go back").action == "back"
    assert parse_step("reload").action == "reload"
    assert parse_step("the total should update to $20") is None  # a check, not an action
    assert parse_step("") is None


# --- running a saved plan -----------------------------------------------------

class _FakeSession:
    """The bits of a live Session a plan walk touches — no adapter, no sandbox."""

    def __init__(self, labels=("Save",), texts=("Saved",), ready=True):
        self.record = SimpleNamespace(id="ses_run", findings=[], surface=SimpleNamespace(value="web"))
        self.last_elements = [Element(id=i, label=lbl, bbox=[0, 0, 1, 1])
                              for i, lbl in enumerate(labels)]
        self.texts = list(texts)
        self.acts: list[tuple] = []
        self._ready = ready

    def launch(self, dev_command=None):
        return self._ready

    def observe(self):
        return b"", self.last_elements, []

    def act(self, at, target_id=None, text=None, key=None, coords=None, url=""):
        self.acts.append((at.value, target_id, text, url))

    def observation_context(self, labels=frozenset()):
        return {"texts": self.texts, "elements": [], "url": None, "states": {}}


def _stub_manager(monkeypatch, session):
    mgr = SimpleNamespace(create=lambda *a, **k: session, stop=lambda sid: None)
    monkeypatch.setattr("inspector.session.SessionManager", lambda config: mgr)


def test_run_scenario_passes_when_the_oracle_passes():
    plan = build_plan("ses_1", "g", [{
        "title": "Save", "steps": ['click "Save"'],
        "assertions": [{"kind": "text", "target": "Saved"}],
    }])
    session = _FakeSession()
    run = run_scenario(session, plan.scenarios[0])
    assert run.status == ScenarioStatus.PASSED
    assert session.acts[0][0] == "click"


def test_run_scenario_fails_when_the_oracle_fails():
    plan = build_plan("ses_1", "g", [{
        "title": "Save", "steps": ['click "Save"'],
        "assertions": [{"kind": "text", "target": "Saved"}],
    }])
    run = run_scenario(_FakeSession(texts=["nothing happened"]), plan.scenarios[0])
    assert run.status == ScenarioStatus.FAILED and "oracle failed" in run.notes


def test_run_scenario_blocks_when_the_ui_no_longer_has_the_step():
    plan = build_plan("ses_1", "g", [{"title": "Save", "steps": ['click "Save"']}])
    run = run_scenario(_FakeSession(labels=["Something else"]), plan.scenarios[0])
    assert run.status == ScenarioStatus.BLOCKED and "step 1/1" in run.notes


def test_run_scenario_blocks_when_no_step_is_an_instruction():
    plan = build_plan("ses_1", "g", [{"title": "Save", "steps": ["it should just work"]}])
    run = run_scenario(_FakeSession(), plan.scenarios[0])
    assert run.status == ScenarioStatus.BLOCKED and "no executable steps" in run.notes


def test_run_scenario_fails_on_a_finding_filed_while_it_walked():
    plan = build_plan("ses_1", "g", [{
        "title": "Save", "steps": ['click "Save"'],
        "assertions": [{"kind": "text", "target": "Saved"}],
    }])
    session = _FakeSession()

    def _act(at, target_id=None, text=None, key=None, coords=None, url=""):
        session.record.findings.append("fnd_new")   # the log tap files one mid-step

    session.act = _act
    run = run_scenario(session, plan.scenarios[0])
    assert run.status == ScenarioStatus.FAILED and run.finding_ids == ["fnd_new"]


def test_run_plan_walks_the_saved_scenarios_and_records_the_run(monkeypatch, tmp_path):
    repo = str(tmp_path / "app")
    os.makedirs(repo)
    config = Config(trace_root=str(tmp_path / "traces"))
    plan = build_plan("ses_old", "checkout", [{
        "title": "Save", "steps": ['click "Save"'],
        "assertions": [{"kind": "text", "target": "Saved"}],
    }], repo_path=repo)
    plan.scenarios[0].record_run(ScenarioStatus.PASSED, session_id="ses_old")
    save_plan(config.trace_root, plan)

    # the button is gone on this build → the scenario that used to pass now fails
    session = _FakeSession(labels=["Save"], texts=["nothing happened"])
    _stub_manager(monkeypatch, session)
    out = run_plan(config, repo, plan.id)

    assert out["status"] == "ran" and out["totals"] == {"failed": 1}
    assert [r["title"] for r in out["regressions"]] == ["Save"]
    saved = load_plan(config.trace_root, repo, plan.id)
    assert [r.session_id for r in saved.scenarios[0].history] == ["ses_old", "ses_run"]
    assert saved.runs == ["ses_run"]


def test_run_plan_reports_an_unknown_plan_and_an_app_that_never_booted(monkeypatch, tmp_path):
    repo = str(tmp_path / "app")
    os.makedirs(repo)
    config = Config(trace_root=str(tmp_path / "traces"))
    out = run_plan(config, repo, "plan_missing")
    assert out["status"] == "not_run" and "no saved plan" in out["error"]

    plan = build_plan("ses_old", "g", [{"title": "Save", "steps": ['click "Save"']}],
                      repo_path=repo)
    save_plan(config.trace_root, plan)
    _stub_manager(monkeypatch, _FakeSession(ready=False))
    out = run_plan(config, repo, plan.id)
    assert out["status"] == "not_run" and "ready" in out["error"]
    # a run that never happened must not be recorded against the plan
    assert load_plan(config.trace_root, repo, plan.id).runs == []


def test_run_plan_saves_the_plan_even_when_a_scenario_explodes(monkeypatch, tmp_path):
    repo = str(tmp_path / "app")
    os.makedirs(repo)
    config = Config(trace_root=str(tmp_path / "traces"))
    plan = build_plan("ses_old", "g", [{"title": "Save", "steps": ['click "Save"']}],
                      repo_path=repo)
    save_plan(config.trace_root, plan)

    session = _FakeSession()

    def _boom(*a, **k):
        raise RuntimeError("transport died")

    session.observe = _boom
    _stub_manager(monkeypatch, session)
    out = run_plan(config, repo, plan.id)
    assert out["totals"] == {"blocked": 1}
    saved = load_plan(config.trace_root, repo, plan.id)
    assert saved.scenarios[0].status == ScenarioStatus.BLOCKED


def test_saved_plan_is_plain_json(tmp_path):
    plan = build_plan("ses_1", "g", [{"title": "Save",
                                      "assertions": [Assertion(kind=AssertionKind.TEXT,
                                                               target="Saved")]}],
                      repo_path=str(tmp_path))
    path = save_plan(str(tmp_path / "traces"), plan)
    with open(path) as f:
        raw = json.load(f)
    assert raw["scenarios"][0]["assertions"][0]["target"] == "Saved"
