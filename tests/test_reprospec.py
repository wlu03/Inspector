"""ReproSpec: a durable, replayable spec attached to every finding (P0.1)."""

from inspector.assertions import Assertion, AssertionKind
from inspector.findings import build_repro_spec
from inspector.models import Finding, ReproSpec, ReproStep, Surface


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


def test_build_repro_spec_accepts_oracle():
    oracle = [Assertion(kind=AssertionKind.TEXT, target="Saved")]
    spec = build_repro_spec(_FakeSession(), oracle=oracle)
    assert spec.oracle[0].target == "Saved"


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
