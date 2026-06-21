"""Per-session Fix-with-Devin: one PR for all of a run's findings."""
from __future__ import annotations

import json

from inspector.config import Config
from inspector.devin import build_session_fix_prompt, fix_session_with_devin


def test_build_session_fix_prompt_lists_all():
    findings = [
        {"severity": "high", "summary": "Plus adds 2", "expected": "+1", "actual": "+2"},
        {"severity": "medium", "summary": "Total ignores price", "expected": "$28", "actual": "$3"},
    ]
    p = build_session_fix_prompt(findings, "examples/sample-buggy-ios", "ios", repo="wlu03/LoopBack")
    assert "Plus adds 2" in p and "Total ignores price" in p
    assert "wlu03/LoopBack" in p and "SINGLE PULL REQUEST" in p
    assert "2 bug(s)" in p


def test_fix_session_excludes_dismissed_and_stamps(tmp_path):
    sid = "ses_x"
    sd = tmp_path / sid
    (sd / "findings").mkdir(parents=True)
    (sd / "session.json").write_text(json.dumps(
        {"id": sid, "repo_path": "examples/sample-buggy-ios", "surface": "ios"}))
    (sd / "findings" / "f1.json").write_text(json.dumps(
        {"id": "f1", "summary": "Real bug", "severity": "high"}))
    (sd / "findings" / "f2.json").write_text(json.dumps(
        {"id": "f2", "summary": "Refuted", "status": "dismissed"}))

    seen = {}

    def fake_api(cfg, method, path, payload=None):
        seen["prompt"] = payload["prompt"]
        return {"url": "http://devin/x", "session_id": "devin-1"}

    cfg = Config(devin_api_key="k", trace_root=str(tmp_path))
    res = fix_session_with_devin(cfg, str(tmp_path), sid, _api_fn=fake_api)

    assert res["status"] == "fixing" and res["n_findings"] == 1   # dismissed excluded
    assert "Real bug" in seen["prompt"] and "Refuted" not in seen["prompt"]
    assert json.loads((sd / "findings" / "f1.json").read_text())["status"] == "fixing"


def test_fix_session_no_findings(tmp_path):
    sid = "ses_y"
    sd = tmp_path / sid
    (sd / "findings").mkdir(parents=True)
    (sd / "session.json").write_text(json.dumps({"id": sid, "surface": "web"}))
    cfg = Config(devin_api_key="k", trace_root=str(tmp_path))
    res = fix_session_with_devin(cfg, str(tmp_path), sid, _api_fn=lambda *a, **k: {})
    assert "error" in res and "no fixable" in res["error"]
