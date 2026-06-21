"""Devin auto-fix: prompt/payload/PR-parse (pure) + fix/poll orchestration (faked API)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

from inspector import devin
from inspector.dashboard.aggregate import finding_signature
from inspector.dashboard.render import render_index


def _cfg(key="apk_test"):
    return SimpleNamespace(devin_api_key=key, devin_base_url="https://api.devin.ai",
                           devin_max_acu=None)


# --- pure helpers ------------------------------------------------------------

def test_build_fix_prompt_has_repo_and_pr_instruction():
    f = {"summary": "Save does nothing", "expected": "toast", "actual": "none",
         "suspected_area": "App.jsx:10", "repro": ["click Save"], "id": "f1"}
    p = devin.build_fix_prompt(f, "/repo/app", "web")
    assert "Save does nothing" in p and "/repo/app" in p
    assert "PULL REQUEST" in p.upper()


def test_build_create_payload():
    p = devin.build_create_payload("do it", "Fix: thing", 5)
    assert p == {"prompt": "do it", "idempotent": True, "title": "Fix: thing", "max_acu_limit": 5}
    assert "max_acu_limit" not in devin.build_create_payload("x", "t", None)


def test_extract_pr_url_across_shapes():
    assert devin.extract_pr_url({"pull_request": {"url": "https://github.com/a/b/pull/3"}}) \
        == "https://github.com/a/b/pull/3"
    assert devin.extract_pr_url({"pull_request_url": "https://x/pull/1"}) == "https://x/pull/1"
    assert devin.extract_pr_url(
        {"structured_output": {"pr": "https://github.com/a/b/pull/9"}}) \
        == "https://github.com/a/b/pull/9"
    assert devin.extract_pr_url({"status": "running"}) is None


# --- orchestration with a faked Devin API ------------------------------------

def _session_with_finding(root, sid, finding):
    sdir = os.path.join(root, sid)
    os.makedirs(os.path.join(sdir, "findings"), exist_ok=True)
    with open(os.path.join(sdir, "session.json"), "w") as f:
        json.dump({"id": sid, "surface": "web", "goal": "g", "state": "torn_down",
                   "repo_path": "/repo", "created_at": "2026-06-21T00:00:00"}, f)
    with open(os.path.join(sdir, "findings", "f0.json"), "w") as f:
        json.dump(finding, f)
    return os.path.join(sdir, "findings", "f0.json")


def test_fix_with_devin_needs_a_key(tmp_path):
    out = devin.fix_with_devin(_cfg(key=None), str(tmp_path), "sig")
    assert "error" in out and "DEVIN_API_KEY" in out["error"]


def test_fix_with_devin_starts_session_and_marks_fixing(tmp_path):
    root = str(tmp_path)
    finding = {"id": "f0", "summary": "Save broken", "severity": "high",
               "suspected_area": "App.jsx:10", "status": "open"}
    path = _session_with_finding(root, "ses_a", finding)
    sig = finding_signature(finding)

    calls = {}

    def fake_api(cfg, method, p, payload=None):
        calls["method"], calls["path"], calls["payload"] = method, p, payload
        return {"session_id": "dev-1", "url": "https://app.devin.ai/sessions/dev-1"}

    out = devin.fix_with_devin(_cfg(), root, sig, _api_fn=fake_api)
    assert out["status"] == "fixing" and out["devin_url"].endswith("dev-1")
    assert calls["method"] == "POST" and calls["path"] == "/v1/sessions"
    # the finding on disk is now tagged so the ledger shows 'fixing' + the Devin link
    data = json.load(open(path))
    assert data["status"] == "fixing" and data["devin_session_id"] == "dev-1"


def test_poll_devin_records_pr_url(tmp_path):
    root = str(tmp_path)
    finding = {"id": "f0", "summary": "Save broken", "severity": "high",
               "suspected_area": "App.jsx:10", "status": "fixing", "devin_session_id": "dev-1"}
    path = _session_with_finding(root, "ses_a", finding)

    def fake_api(cfg, method, p, payload=None):
        assert method == "GET" and p == "/v1/session/dev-1"
        return {"status_enum": "finished",
                "pull_request": {"url": "https://github.com/a/b/pull/7"}}

    out = devin.poll_devin(_cfg(), root, "dev-1", _api_fn=fake_api)
    assert out["pr_url"] == "https://github.com/a/b/pull/7"
    assert json.load(open(path))["pr_url"] == "https://github.com/a/b/pull/7"


# --- dashboard renders the button + PR link ----------------------------------

def test_ledger_renders_fix_button_for_any_bug():
    ledger = [
        {"signature": "s1", "summary": "open bug", "severity": "high", "suspected_area": "a:1",
         "status": "open", "occurrences": 1, "sessions": ["x"], "devin_url": None, "pr_url": None},
        {"signature": "s2", "summary": "verified bug", "severity": "low", "suspected_area": "b:2",
         "status": "verified", "occurrences": 1, "sessions": ["x"], "devin_url": None, "pr_url": None},
        {"signature": "s3", "summary": "has pr", "severity": "high", "suspected_area": "c:3",
         "status": "fixing", "occurrences": 1, "sessions": ["x"],
         "devin_url": "https://app.devin.ai/s/3", "pr_url": "https://github.com/a/b/pull/3"},
    ]
    stats = {"n_sessions": 1, "findings_total": 3, "by_severity": {}, "pass_rate": None}
    html = render_index([], stats, [], ledger=ledger, update={})
    assert html.count(">Fix with Devin</button>") == 2  # open + verified both get the button
    assert "devinFix(this)" in html and "data-sig='s1'" in html
    assert "PR ↗" in html and "pull/3" in html         # the one with a PR shows the link
    assert "api/devin-fix" in html and "pollDevin" in html
