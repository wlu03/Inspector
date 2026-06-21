"""Tests for the close-the-loop re-verify core."""
from __future__ import annotations

import json

from inspector.models import ActionType
from inspector.reverify import load_actions, mark_fixed, replay_actions, signature_present


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
