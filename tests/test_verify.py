"""Tests for adversarial verification + the new-finding progress signal."""
from __future__ import annotations

import json
import os

from inspector.driver import build_refute_prompt, parse_refute_verdict
from inspector.loop import LoopGuard
from inspector.verify import confirmed_findings, verify_findings


# --- refute prompt + parser (pure) ---

def test_refute_prompt_and_parser():
    p = build_refute_prompt({"severity": "high", "summary": "ghost button", "actual": "b"})
    assert "REFUTE" in p and "ghost button" in p
    assert parse_refute_verdict('{"confirmed": true, "reason": "real"}')["confirmed"] is True
    assert parse_refute_verdict("not json")["confirmed"] is False  # skeptical default


# --- verify_findings: refute judgment findings, trust log facts ---

class _Trace:
    def __init__(self, d):
        self.findings_dir = os.path.join(d, "findings")
        self.frames_dir = os.path.join(d, "frames")
        os.makedirs(self.findings_dir)
        os.makedirs(self.frames_dir)


class _Sess:
    def __init__(self, d):
        self.trace = _Trace(d)


class _Driver:
    def verify_finding(self, finding, shot):
        return {"confirmed": "real" in finding.get("summary", ""), "reason": "x"}


def _write(sess, fid, **fields):
    with open(os.path.join(sess.trace.findings_dir, f"{fid}.json"), "w") as f:
        json.dump({"id": fid, **fields}, f)


def test_verify_refutes_judgment_keeps_facts(tmp_path):
    sess = _Sess(str(tmp_path))
    _write(sess, "f1", summary="TypeError boom", logs=["TypeError boom"])  # deterministic fact
    _write(sess, "f2", summary="maybe odd layout", screenshot_refs=[])     # judgment → refuted
    _write(sess, "f3", summary="real broken button", screenshot_refs=[])   # judgment → confirmed

    v = verify_findings(sess, _Driver())
    assert v == {"verified": 1, "dismissed": 1, "trusted": 1}

    assert {f["id"] for f in confirmed_findings(sess)} == {"f1", "f3"}  # f2 dropped

    with open(os.path.join(sess.trace.findings_dir, "f2.json")) as f:
        dismissed = json.load(f)
    assert dismissed["status"] == "dismissed" and dismissed["confidence"] == "low"


def test_verify_noops_without_brain(tmp_path):
    sess = _Sess(str(tmp_path))
    _write(sess, "f1", summary="x", screenshot_refs=[])

    class _NoBrain:
        pass
    assert verify_findings(sess, _NoBrain()) == {"verified": 0, "dismissed": 0, "trusted": 0}


# --- a fresh finding counts as progress (no-progress no longer trips on buggy-but-quiet UI) ---

def test_new_finding_resets_no_progress():
    g = LoopGuard(no_progress_limit=2)
    g.observe_state(b"same", signal=False)
    g.observe_state(b"same", signal=False)   # _repeat = 1
    assert g._repeat == 1
    g.observe_state(b"same", signal=True)    # a finding this step → progress
    assert g._repeat == 0
