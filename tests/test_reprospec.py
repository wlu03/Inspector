"""ReproSpec: a durable, replayable spec attached to every finding (P0.1)."""

import json
from types import SimpleNamespace

import inspector.server as server
from inspector.assertions import Assertion, AssertionKind, AssertionOp
from inspector.findings import build_repro_spec
from inspector.models import (
    ActionType,
    Element,
    Finding,
    ReproSpec,
    ReproStep,
    SessionRecord,
    Surface,
)
from inspector.session import Session
from inspector.trace import TraceRecorder


class _FakeRecord:
    surface = Surface.WEB


class _FakeAdapter:
    cdp = None  # no CDP -> no route captured


class _FakeSession:
    action_log = ["click element #0 (Save)", "type 'hello'", "press 'Enter'", "scroll down"]
    record = _FakeRecord()
    adapter = _FakeAdapter()


def test_build_repro_spec_parses_semantic_steps():
    spec = build_repro_spec(_FakeSession())
    assert spec.steps[0].action == "click" and spec.steps[0].locator == "Save"
    assert any(s.action == "type" and s.text == "hello" for s in spec.steps)
    assert any(s.action == "key" and s.key == "Enter" for s in spec.steps)
    assert spec.surface == "web"
    assert "surface=web" in spec.preconditions


def _round_trip(*steps) -> list[ReproStep]:
    """Render actions the way `Session.act` logs them, then parse that log back.

    The action log is the only carrier between an action and the repro spec attached to
    every finding, so anything that does not survive this pair is silently unreplayable.
    """
    session = Session.__new__(Session)
    session.record = _FakeRecord()
    session.adapter = _FakeAdapter()
    session.last_elements = [
        Element(id=0, label="Card", bbox=[0.1, 0.1, 0.2, 0.2]),
        Element(id=1, label="Done column", bbox=[0.8, 0.8, 0.9, 0.9]),
    ]
    session.action_log = [session._describe_action(*args, **kwargs) for args, kwargs in steps]
    return build_repro_spec(session).steps


def test_a_drag_round_trips_through_the_action_log():
    [step] = _round_trip(((ActionType.DRAG, 0, None, None), {"to_id": 1}))
    assert step.action == "drag"
    assert step.locator == "Card" and step.to_locator == "Done column"


def test_a_drag_to_raw_coordinates_still_records_where_it_went():
    [step] = _round_trip(((ActionType.DRAG, 0, None, None), {"to_coords": [640, 480]}))
    assert step.action == "drag" and step.to_locator == "(640, 480)"


def test_a_navigate_round_trips_through_the_action_log():
    # the one that MUST survive: a repro spec that lost its navigation replays the
    # whole scenario on whatever page the app booted on, and quietly reproduces nothing
    [step] = _round_trip(
        ((ActionType.NAVIGATE, None, None, None), {"url": "http://localhost:3000/settings"})
    )
    assert step.action == "navigate"
    assert step.url == "http://localhost:3000/settings"


def test_history_and_pointer_actions_round_trip():
    steps = _round_trip(
        ((ActionType.BACK, None, None, None), {}),
        ((ActionType.FORWARD, None, None, None), {}),
        ((ActionType.RELOAD, None, None, None), {}),
        ((ActionType.HOVER, 0, None, None), {}),
        ((ActionType.RIGHT_CLICK, 1, None, None), {}),
    )
    assert [s.action for s in steps] == ["back", "forward", "reload", "hover", "right_click"]
    assert steps[3].locator == "Card" and steps[4].locator == "Done column"
    # every parsed action is a real ActionType, i.e. something a replay can dispatch
    assert all(ActionType(s.action) for s in steps)


def test_a_targetless_pointer_action_is_still_a_real_action_type():
    [step] = _round_trip(((ActionType.RIGHT_CLICK, None, None, None), {}))
    assert step.action == "right_click" and ActionType(step.action) is ActionType.RIGHT_CLICK


def test_a_scroll_records_the_direction_it_was_aimed():
    # the direction has to land in a FIELD, not in the verb: `replay_spec` dispatches on
    # the action name, and "scroll up" is not an ActionType, so it would replay as a wait
    [up, down] = _round_trip(
        ((ActionType.SCROLL, None, None, None), {"direction": "up"}),
        ((ActionType.SCROLL, None, None, None), {}),
    )
    assert (up.action, up.direction) == ("scroll", "up")
    assert (down.action, down.direction) == ("scroll", "down")
    assert ActionType(up.action) is ActionType.SCROLL


def test_build_repro_spec_accepts_oracle():
    oracle = [Assertion(kind=AssertionKind.TEXT, target="Saved")]
    spec = build_repro_spec(_FakeSession(), oracle=oracle)
    assert spec.oracle[0].target == "Saved"


def test_build_repro_spec_inherits_the_sessions_last_assertions():
    # a finding filed after a failing check_assertions should carry that check as its
    # oracle rather than nothing at all
    session = _FakeSession()
    session.last_assertions = [Assertion(kind=AssertionKind.TEXT, target="Saved")]
    assert build_repro_spec(session).oracle[0].target == "Saved"
    # an explicitly-passed oracle always wins over the inherited one
    explicit = [Assertion(kind=AssertionKind.URL, target="/done", op=AssertionOp.CONTAINS)]
    assert build_repro_spec(session, oracle=explicit).oracle[0].target == "/done"


def test_build_repro_spec_without_any_oracle_is_empty():
    assert build_repro_spec(_FakeSession()).oracle == []


def test_finding_carries_repro_spec_and_round_trips():
    spec = ReproSpec(surface="web", steps=[ReproStep(action="click", locator="Save")],
                     oracle=[Assertion(kind=AssertionKind.TEXT, target="Saved")])
    f = Finding(summary="Save silently fails", repro_spec=spec)
    assert f.repro_spec.steps[0].locator == "Save"
    assert f.repro_spec.oracle[0].kind == AssertionKind.TEXT
    # findings are persisted as JSON, so the spec must round-trip
    back = Finding.model_validate_json(f.model_dump_json())
    assert back.repro_spec.surface == "web"
    assert back.repro_spec.oracle[0].target == "Saved"


class _StubSession:
    """Only what the report_issue / check_assertions tools actually touch on a Session —
    a real one would need an adapter, a detector and a live app."""

    def __init__(self, trace_root: str):
        self.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)
        self.trace = TraceRecorder(trace_root, self.record.id)
        self.adapter = SimpleNamespace(cdp=None)
        self.action_log = ["click element #0 (Save)"]
        self.last_assertions = []

    def touch(self) -> None:
        pass

    def observe(self):
        return b"", [], []


def _with_session(tmp_path):
    session = _StubSession(str(tmp_path))
    server.MANAGER.sessions[session.record.id] = session
    return session


def _saved_finding(tmp_path, session, finding_id: str) -> dict:
    path = tmp_path / session.record.id / "findings" / f"{finding_id}.json"
    return json.loads(path.read_text())


def test_report_issue_threads_its_assertions_onto_the_repro_spec(tmp_path):
    session = _with_session(tmp_path)
    try:
        out = server.report_issue(
            session.record.id, "Save silently fails",
            assertions=[Assertion(kind=AssertionKind.TEXT, target="Saved")],
        )
    finally:
        server.MANAGER.sessions.pop(session.record.id, None)
    saved = _saved_finding(tmp_path, session, out["finding_id"])
    # the oracle is the CORRECT behavior and it survives the trip through JSON
    assert saved["repro_spec"]["oracle"] == [
        {"kind": "text", "target": "Saved", "op": "present", "expected": None, "on": ""}
    ]


def test_report_issue_inherits_the_last_checked_assertions(tmp_path):
    session = _with_session(tmp_path)
    session.last_assertions = [Assertion(kind=AssertionKind.TEXT, target="Saved")]
    try:
        out = server.report_issue(session.record.id, "Save silently fails")
    finally:
        server.MANAGER.sessions.pop(session.record.id, None)
    saved = _saved_finding(tmp_path, session, out["finding_id"])
    assert saved["repro_spec"]["oracle"][0]["target"] == "Saved"


def test_check_assertions_records_what_it_evaluated(tmp_path):
    session = _with_session(tmp_path)
    oracle = [Assertion(kind=AssertionKind.TEXT, target="Saved")]
    try:
        out = server.check_assertions(session.record.id, oracle)
    finally:
        server.MANAGER.sessions.pop(session.record.id, None)
    assert out["overall"] == "fail"  # nothing on screen -> the check really ran
    assert session.last_assertions == oracle
