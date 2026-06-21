from inspector.driver import Decision, FallbackDriver, HeuristicDriver, _is_degenerate
from inspector.models import Element


def _els():
    return [Element(id=1, label="Your name", role="icon", bbox=[0.0, 0.0, 0.5, 0.1], interactivity=True)]


class _Primary:
    def __init__(self, decision):
        self._d = decision

    def decide(self, *a):
        return self._d


def test_is_degenerate_unit():
    assert _is_degenerate(Decision(action="wait"))
    assert _is_degenerate(Decision(action="type", text=""))
    assert _is_degenerate(Decision(action="type", text="   "))
    assert _is_degenerate(Decision(action="click", target_id=None))
    assert _is_degenerate(Decision(action="key", key=""))
    assert not _is_degenerate(Decision(action="click", target_id=1))
    assert not _is_degenerate(Decision(action="type", target_id=1, text="hi"))
    assert not _is_degenerate(Decision(action="done"))


def test_empty_type_falls_back_to_heuristic():
    # the heuristic may itself type an empty string (a deliberate edge-input case),
    # so prove the fallback fired via a marker, not by asserting non-empty text.
    primary = _Primary(Decision(action="type", target_id=1, text="", reason="PRIMARY"))
    d = FallbackDriver(primary, HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.reason != "PRIMARY"          # routed to the heuristic, not the no-op
    assert d.target_id == 1               # heuristic engaged the field


def test_targetless_click_falls_back():
    primary = _Primary(Decision(action="click", target_id=None))
    d = FallbackDriver(primary, HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.target_id is not None


def test_valid_action_passes_through():
    primary = _Primary(Decision(action="click", target_id=1, reason="vlm"))
    d = FallbackDriver(primary, HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.reason == "vlm" and d.target_id == 1


def test_done_passes_through():
    primary = _Primary(Decision(action="done"))
    d = FallbackDriver(primary, HeuristicDriver()).decide(b"", _els(), "g", [], [])
    assert d.is_done
