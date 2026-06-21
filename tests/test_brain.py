"""Tests for the driver-default + keyboard-filter improvements."""
from __future__ import annotations

from inspector.autopilot import _confine, _is_keyboard_key
from inspector.config import Config
from inspector.driver import AnthropicDriver, FallbackDriver, ReplicateDriver, get_driver
from inspector.models import Element


def _el(label, role="button"):
    return Element(id=0, label=label, role=role, bbox=[0, 0, 0.1, 0.1], interactivity=True)


# --- soft-keyboard filtering ---

def test_keyboard_keys_are_filtered():
    els = [_el("Save"), _el("Q"), _el("space"), _el("a"), _el("return"), _el("k", role="key")]
    assert [e.label for e in _confine(els)] == ["Save"]


def test_real_controls_kept():
    assert [e.label for e in _confine([_el("Checkout"), _el("Profile")])] == ["Checkout", "Profile"]


def test_is_keyboard_key():
    assert _is_keyboard_key(_el("Q")) and _is_keyboard_key(_el("space"))
    assert not _is_keyboard_key(_el("Save")) and not _is_keyboard_key(_el("OK"))


# --- driver default: auto prefers Claude when a key is present ---

def test_auto_prefers_anthropic_with_key():
    d = get_driver(Config(anthropic_api_key="sk-x", driver_backend="auto"))
    assert isinstance(d, FallbackDriver) and isinstance(d.primary, AnthropicDriver)


def test_auto_falls_to_replicate_without_key():
    d = get_driver(Config(anthropic_api_key=None, driver_backend="auto"))
    assert isinstance(d, FallbackDriver) and isinstance(d.primary, ReplicateDriver)


def test_default_backend_is_auto():
    assert Config().driver_backend == "auto"


# --- de-repetition: a stuck brain gets pushed to fresh elements, then stops ---

def test_derep_explores_then_stops():
    from inspector.autopilot import _next_unvisited, run_autopilot
    from inspector.driver import Decision
    from inspector.loop import LoopGuard
    from inspector.models import Surface

    els = [_el("Alpha"), _el("Beta")]  # multi-char so the keyboard filter keeps them
    els[0].id, els[1].id = 0, 1
    assert _next_unvisited(els, {0}) == 1  # id 0 acted → pick the next interactive

    class _Trace:
        findings_dir = "/nonexistent"
        _frame_n = 0

    class _Rec:
        id = "s"
        trace_id = "t"
        repo_path = "/x"
        surface = Surface.WEB

        def __init__(self):
            self.findings = []

    class _Sess:
        def __init__(self):
            self.last_elements = els
            self.guard = LoopGuard(max_iterations=50, max_wall_clock_s=9999)
            self.trace = _Trace()
            self.record = _Rec()

        def observe(self):
            return b"", els, []

        def act(self, *a):
            self.guard.tick()
            return b"", False, []   # every action is a no-op → forces de-rep

        def audit(self):
            return {}, []

    class _StuckDriver:
        def decide(self, *a):
            return Decision(action="click", target_id=0)  # always the same element

    report = run_autopilot(_Sess(), _StuckDriver(), goal="x")
    # both elements acted on once, then nothing left → "explored" (not the iteration cap)
    assert report["stop_reason"] == "explored"
    assert report["steps"] == 2
