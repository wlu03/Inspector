"""Pure tests for the autopilot brain + loop — no sandbox, no Replicate."""
from __future__ import annotations

from inspector.autopilot import run_autopilot
from inspector.driver import DONE, Decision, build_decision_prompt, parse_decision
from inspector.loop import LoopGuard
from inspector.models import ActionType, Element


def _el(id, label="", role="icon", interactive=True):
    return Element(id=id, label=label, role=role, bbox=[0, 0, 0.1, 0.1], interactivity=interactive)


# --- prompt building ---

def test_prompt_includes_goal_elements_and_protocol():
    els = [_el(0, "Save"), _el(1, "Your name", role="text")]
    prompt = build_decision_prompt("test save", els, history=[], logs=["boom error"])
    assert "test save" in prompt
    assert "[0]" in prompt and "Save" in prompt
    assert "boom error" in prompt
    assert '"action"' in prompt  # the JSON protocol is spelled out


# --- decision parsing ---

def test_parse_plain_json():
    d = parse_decision('{"action": "click", "target_id": 2, "reason": "save it"}')
    assert d.action == "click" and d.target_id == 2 and d.reason == "save it"
    assert d.action_type() == ActionType.CLICK


def test_parse_strips_code_fence_and_prose():
    raw = 'Sure!\n```json\n{"action": "type", "target_id": 1, "text": "hi"}\n```'
    d = parse_decision(raw)
    assert d.action == "type" and d.text == "hi"


def test_parse_unknown_action_falls_back_to_wait():
    d = parse_decision('{"action": "teleport"}')
    assert d.action == "wait"


def test_parse_drops_hallucinated_target_id():
    d = parse_decision('{"action": "click", "target_id": 99}', elements=[_el(0), _el(1)])
    assert d.target_id is None  # 99 isn't in the element list


def test_parse_keeps_bug_only_when_summarized():
    d = parse_decision('{"action": "done", "bug": {"summary": "crash", "severity": "high"}}')
    assert d.is_done and d.bug and d.bug["summary"] == "crash"
    empty = parse_decision('{"action": "done", "bug": {"summary": ""}}')
    assert empty.bug is None


def test_parse_garbage_is_safe():
    assert parse_decision("not json at all").action == "wait"


# --- the loop, driven by a scripted fake ---

class _FakeTrace:
    def __init__(self):
        self.findings_dir = "/nonexistent"  # collect_findings tolerates a missing dir
        self.saved = []
        self._frame_n = 3

    def save_finding(self, finding):
        self.saved.append(finding)


class _FakeRecord:
    id = "ses_test"
    trace_id = "trc_test"

    def __init__(self):
        self.findings = []


class _FakeSession:
    """Minimal stand-in for Session: counts observe/act and replays a script."""

    def __init__(self, elements):
        self.last_elements = elements
        self.guard = LoopGuard(max_iterations=10, max_wall_clock_s=9999)
        self.trace = _FakeTrace()
        self.record = _FakeRecord()
        self.acts = []

    def observe(self):
        return b"png", self.last_elements, []

    def act(self, action_type, target_id, text, key):
        self.guard.tick()
        self.acts.append((action_type, target_id, text))
        return b"png2", True, []


class _ScriptedDriver:
    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def decide(self, som, elements, goal, history, logs):
        self.calls += 1
        if self._decisions:
            return self._decisions.pop(0)
        return Decision(action=DONE)


def test_loop_acts_then_stops_on_done():
    session = _FakeSession([_el(0, "Save")])
    driver = _ScriptedDriver([
        Decision(action="click", target_id=0, reason="hit save"),
        Decision(action=DONE, reason="seen enough"),
    ])
    report = run_autopilot(session, driver, goal="test")
    assert report["stop_reason"] == "model_done"
    assert report["steps"] == 1
    assert session.acts == [(ActionType.CLICK, 0, None)]
    assert report["history"][0]["target_label"] == "Save"


def test_loop_records_bug_finding():
    session = _FakeSession([_el(0, "Save")])
    driver = _ScriptedDriver([
        Decision(action=DONE, bug={"summary": "no toast", "severity": "high"}),
    ])
    run_autopilot(session, driver, goal="test")
    assert len(session.trace.saved) == 1
    assert session.trace.saved[0].summary == "no toast"
    assert session.record.findings == [session.trace.saved[0].id]


def test_loop_stops_on_guard_max_iterations():
    session = _FakeSession([_el(0)])
    # never returns DONE → only the guard can stop it
    driver = _ScriptedDriver([Decision(action="click", target_id=0) for _ in range(100)])
    report = run_autopilot(session, driver, goal="test")
    assert report["stop_reason"] == "max_iterations"
    assert session.guard.iterations == 10


def test_loop_survives_driver_exception():
    class _BoomDriver:
        calls = 0

        def decide(self, *a, **k):
            self.__class__.calls += 1
            if self.calls == 1:
                raise RuntimeError("model down")
            return Decision(action=DONE)

    session = _FakeSession([_el(0)])
    report = run_autopilot(session, _BoomDriver(), goal="test")
    assert report["stop_reason"] == "model_done"  # recovered, then finished
