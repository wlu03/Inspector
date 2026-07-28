"""Tests for the close-the-loop re-verify core."""
from __future__ import annotations

import json
from types import SimpleNamespace

import inspector.server as server
from inspector.assertions import Assertion, AssertionKind
from inspector.models import ActionType, Element, Finding, SessionRecord, Surface
from inspector.reverify import load_actions, mark_fixed, replay_actions, signature_present
from inspector.trace import TraceRecorder


def test_signature_present_normalizes_digits():
    found = [{"summary": "Save crashed at line 88"}]
    assert signature_present(found, "Save crashed at line 42")   # digits collapse → same bug
    assert not signature_present(found, "A different bug")


def test_replay_skips_clickless_and_invalid():
    class _S:
        def __init__(self):
            self.calls = []

        def act(self, t, coords=None, text=None, key=None):
            self.calls.append((t, coords, text))

    s = _S()
    n = replay_actions(s, [
        {"type": "click", "coords": [10, 20]},
        {"type": "click"},               # no coords → skipped
        {"type": "type", "text": "hi"},  # type allowed without coords
        {"type": "bogus"},               # invalid type → skipped
    ])
    assert n == 2
    assert s.calls[0] == (ActionType.CLICK, [10, 20], None)
    assert s.calls[1][0] == ActionType.TYPE


def test_load_actions(tmp_path):
    (tmp_path / "actions.jsonl").write_text('{"type":"click","coords":[1,2]}\n\nnot json\n')
    assert load_actions(str(tmp_path)) == [{"type": "click", "coords": [1, 2]}]


def test_mark_fixed(tmp_path):
    fdir = tmp_path / "findings"
    fdir.mkdir()
    (fdir / "f1.json").write_text(json.dumps(
        {"id": "f1", "summary": "Save crashed at line 8", "status": "open"}))
    n = mark_fixed(str(tmp_path), "Save crashed at line 99", fixed=True)  # digits collapse
    assert n == 1
    assert json.loads((fdir / "f1.json").read_text())["status"] == "fixed"


def test_replay_spec_semantic_and_not_run():
    from inspector.models import Element, ReproSpec, ReproStep
    from inspector.reverify import replay_spec

    class _Sess:
        def __init__(self, labels):
            self.last_elements = [Element(id=i, label=lbl, bbox=[0, 0, 1, 1])
                                  for i, lbl in enumerate(labels)]
            self.acts = []

        def observe(self):
            return b"", self.last_elements, []

        def act(self, at, target_id=None, text=None, key=None, coords=None):
            self.acts.append((at.value, target_id, text, key))

    spec = ReproSpec(steps=[ReproStep(action="click", locator="Save"),
                            ReproStep(action="type", text="hi")])
    s = _Sess(["Save", "Name"])
    assert replay_spec(s, spec) == (2, 2)
    assert s.acts[0][0] == "click" and s.acts[1][0] == "type"

    # a missing locator -> the scenario diverges (not fully reached)
    spec2 = ReproSpec(steps=[ReproStep(action="click", locator="Missing"),
                             ReproStep(action="click", locator="Save")])
    assert replay_spec(_Sess(["Save"]), spec2) == (0, 2)


class _ReplaySession:
    """The freshly-launched session verify_fix_spec drives on the post-fix build."""

    def __init__(self, texts: list[str]):
        self.record = SimpleNamespace(id="ses_replay")
        self.last_elements = [Element(id=0, label="Save", bbox=[0, 0, 1, 1])]
        self.texts = texts
        self.acts: list[str] = []

    def launch(self) -> bool:
        return True

    def observe(self):
        return b"", self.last_elements, []

    def act(self, at, target_id=None, text=None, key=None, coords=None):
        self.acts.append(at.value)

    def observation_context(self, labels=frozenset()) -> dict:
        return {"texts": self.texts, "elements": [], "url": None, "states": {}}


def _stub_manager(monkeypatch, session):
    """Swap the SessionManager verify_fix_spec builds so nothing is launched."""
    mgr = SimpleNamespace(create=lambda *a, **k: session, stop=lambda sid: None)
    monkeypatch.setattr("inspector.session.SessionManager", lambda config: mgr)


class _FilingSession:
    """Only what report_issue touches on a live Session, with a real on-disk trace."""

    def __init__(self, trace_root: str):
        self.record = SessionRecord(repo_path="/repo", surface=Surface.WEB)
        self.trace = TraceRecorder(trace_root, self.record.id)
        self.adapter = SimpleNamespace(cdp=None)
        self.action_log = ["click element #0 (Save)"]
        self.last_assertions: list[Assertion] = []

    def touch(self) -> None:
        pass


def _file_finding_with_oracle(tmp_path, oracle) -> Finding:
    """Drive the real report_issue tool, then read the finding back off disk — the
    same JSON round trip verify_fix does when it re-verifies a past run."""
    session = _FilingSession(str(tmp_path))
    server.MANAGER.sessions[session.record.id] = session
    try:
        out = server.report_issue(session.record.id, "Save silently fails",
                                  assertions=oracle)
    finally:
        server.MANAGER.sessions.pop(session.record.id, None)
    path = tmp_path / session.record.id / "findings" / f"{out['finding_id']}.json"
    return Finding.model_validate_json(path.read_text())


def test_oracle_survives_the_trace_round_trip_and_decides_the_verdict(monkeypatch, tmp_path):
    oracle = [Assertion(kind=AssertionKind.TEXT, target="Saved")]
    finding = _file_finding_with_oracle(tmp_path, oracle)
    spec = finding.repro_spec
    assert spec.steps[0].locator == "Save"          # the repro replays semantically
    assert spec.oracle[0].target == "Saved"         # ...and the oracle came back intact

    # the old signature check would still say "still_present" — the oracle must win
    monkeypatch.setattr("inspector.reverify.collect_findings",
                        lambda session: [{"summary": finding.summary}])

    from inspector.reverify import verify_fix_spec

    fixed_app = _ReplaySession(texts=["Saved"])
    _stub_manager(monkeypatch, fixed_app)
    out = verify_fix_spec(None, "/repo", spec, finding.summary)
    assert out["status"] == "fixed" and out["oracle"] is True
    assert fixed_app.acts == ["click"]               # the repro really was replayed

    # and the same oracle failing means the bug is still there
    _stub_manager(monkeypatch, _ReplaySession(texts=["nothing happened"]))
    out = verify_fix_spec(None, "/repo", spec, finding.summary)
    assert out["status"] == "still_present" and out["oracle"] is True


def test_no_oracle_falls_back_to_signature_matching(monkeypatch, tmp_path):
    finding = _file_finding_with_oracle(tmp_path, [])
    assert finding.repro_spec.oracle == []
    monkeypatch.setattr("inspector.reverify.collect_findings",
                        lambda session: [{"summary": finding.summary}])

    from inspector.reverify import verify_fix_spec

    _stub_manager(monkeypatch, _ReplaySession(texts=["Saved"]))
    out = verify_fix_spec(None, "/repo", finding.repro_spec, finding.summary)
    assert out["status"] == "still_present" and "oracle" not in out
