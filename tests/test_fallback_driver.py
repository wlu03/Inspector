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
