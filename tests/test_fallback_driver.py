from __future__ import annotations

from inspector.driver import Decision, FallbackDriver, HeuristicDriver
from inspector.models import Element


def _els():
    return [
        Element(id=1, label="Your name", role="icon", bbox=[0.0, 0.0, 0.5, 0.1], interactivity=True),
        Element(id=2, label="Save", role="icon", bbox=[0.5, 0.0, 0.6, 0.1], interactivity=True),
        Element(id=0, label="Settings", role="text", bbox=[0.0, 0.0, 0.3, 0.05], interactivity=False),
    ]


def test_heuristic_visits_each_once_then_done():
    h = HeuristicDriver()
    d1 = h.decide(b"", _els(), "g", [], [])
    assert d1.action == "type" and d1.target_id == 1  # field -> type
    d2 = h.decide(b"", _els(), "g", [], [])
    assert d2.action == "click" and d2.target_id == 2  # button -> click
    assert h.decide(b"", _els(), "g", [], []).is_done   # nothing left


class _Stalled:
    def decide(self, *a):
        return Decision(action="wait", reason="unparseable")


class _Decisive:
    def decide(self, *a):
        return Decision(action="click", target_id=2, reason="vlm")


def test_fallback_used_when_primary_stalls():
    d = FallbackDriver(_Stalled(), HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.action in ("type", "click")  # fell back to heuristic, made progress


def test_primary_used_when_decisive():
    d = FallbackDriver(_Decisive(), HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.action == "click" and d.target_id == 2 and d.reason == "vlm"


class _Boom:
    def decide(self, *a):
        raise RuntimeError("rate limited")


def test_fallback_used_when_primary_raises():
    # an API failure must still advance the run, not waste the step on a no-op
    d = FallbackDriver(_Boom(), HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.action in ("type", "click")


class _Brain:
    """Only the brain-only methods — FallbackDriver must route these to the primary."""

    def judge_missing_element(self, candidate, rendered, screenshot):
        return {"is_bug": True, "severity": "high", "reason": "primary"}

    def verify_finding(self, finding, screenshot):
        return {"confirmed": True, "reason": "primary"}

    def plan(self, som, elements, goal):
        return [{"name": "Settings", "goal": "primary"}]


def test_judgment_calls_delegate_to_primary():
    d = FallbackDriver(_Brain(), HeuristicDriver())
    assert d.judge_missing_element(None, [], b"")["reason"] == "primary"
    assert d.verify_finding({}, b"")["reason"] == "primary"
    assert d.plan(b"", _els(), "g") == [{"name": "Settings", "goal": "primary"}]
