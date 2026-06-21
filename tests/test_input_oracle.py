"""Tests for the input-integrity oracle (type -> read-back mismatch)."""
from __future__ import annotations

import json

from inspector.adapters.ios import describe_value_at
from inspector.autopilot import _check_input_integrity
from inspector.driver import Decision


# --- iOS value reader (pure) ---

def test_describe_value_at():
    nodes = json.dumps([
        {"AXLabel": "Your name", "AXValue": "7", "type": "TextField",
         "frame": {"x": 0, "y": 0, "width": 100, "height": 40}},
        {"AXLabel": "", "type": "Button", "frame": {"x": 0, "y": 50, "width": 80, "height": 40}},
    ])
    assert describe_value_at(nodes, 0)["value"] == "7"
    assert describe_value_at(nodes, 0)["label"] == "Your name"
    assert describe_value_at(nodes, 9) == {}
    assert describe_value_at("garbage", 0) == {}


# --- the autopilot check ---

class _Trace:
    _frame_n = 0

    def __init__(self):
        self.saved = []

    def save_finding(self, f):
        self.saved.append(f)


class _Rec:
    id = "s"
    trace_id = "t"

    def __init__(self):
        self.findings = []


class _Sess:
    def __init__(self, value):
        self.adapter = type("A", (), {"control_state": lambda self, i: {"value": value}})()
        self.trace = _Trace()
        self.record = _Rec()


def test_flags_mismatch():
    s = _Sess("7")   # typed 007, field holds 7  → BUG-02 class
    _check_input_integrity(s, Decision(action="type", target_id=0, text="007"))
    assert len(s.trace.saved) == 1 and "007" in s.trace.saved[0].summary
    assert s.record.findings == [s.trace.saved[0].id]


def test_no_flag_when_value_matches():
    s = _Sess("Wesley")
    _check_input_integrity(s, Decision(action="type", target_id=0, text="Wesley"))
    assert s.trace.saved == []


def test_skips_when_value_not_exposed():
    s = _Sess("")   # field doesn't surface its contents → can't tell, don't false-flag
    _check_input_integrity(s, Decision(action="type", target_id=0, text="007"))
    assert s.trace.saved == []
