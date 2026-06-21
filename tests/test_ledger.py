"""The fix loop: evidence-based bug ledger + latest-run delta + dashboard tab."""
from __future__ import annotations

import json
import os

from inspector.dashboard.aggregate import bug_ledger, latest_update
from inspector.dashboard.render import render_index


def _run(root, sid, created, repo, findings):
    sdir = os.path.join(root, sid)
    os.makedirs(os.path.join(sdir, "findings"), exist_ok=True)
    with open(os.path.join(sdir, "session.json"), "w") as f:
        json.dump({"id": sid, "surface": "web", "goal": "g", "state": "torn_down",
                   "repo_path": repo, "created_at": created}, f)
    for i, fd in enumerate(findings):
        with open(os.path.join(sdir, "findings", f"f{i}.json"), "w") as f:
            json.dump(fd, f)


def _finding(summary, severity="high", status="open"):
    return {"id": summary, "summary": summary, "severity": severity, "status": status,
            "suspected_area": "App.jsx:10"}


def test_ledger_marks_gone_issue_verified_and_present_open(tmp_path):
    root = str(tmp_path)
    # run 1 (older): two bugs. run 2 (newer): only one still reproduces.
    _run(root, "ses_old", "2026-06-01T10:00:00", "/repo",
         [_finding("Save does nothing"), _finding("Console error boom", "critical")])
    _run(root, "ses_new", "2026-06-02T10:00:00", "/repo",
         [_finding("Save does nothing")])
    by_summary = {g["summary"]: g for g in bug_ledger(root)}
    assert by_summary["Save does nothing"]["status"] == "open"        # still present
    assert by_summary["Console error boom"]["status"] == "verified"   # gone → fixed


def test_ledger_respects_manual_dismissed(tmp_path):
    root = str(tmp_path)
    _run(root, "ses_x", "2026-06-01T10:00:00", "/repo",
         [_finding("Flaky thing", status="dismissed")])
    [g] = bug_ledger(root)
    assert g["status"] == "dismissed"


def test_latest_update_reports_fixed_new_and_open(tmp_path):
    root = str(tmp_path)
    _run(root, "ses_old", "2026-06-01T10:00:00", "/repo",
         [_finding("A"), _finding("B")])
    _run(root, "ses_new", "2026-06-02T10:00:00", "/repo",
         [_finding("A"), _finding("C")])  # B fixed, C new, A persists
    upd = latest_update(root)
    assert upd["has_prev"] is True
    assert [x["summary"] for x in upd["verified"]] == ["B"]
    assert [x["summary"] for x in upd["new"]] == ["C"]
    assert [x["summary"] for x in upd["still_open"]] == ["A"]


def test_first_run_has_no_prior_delta(tmp_path):
    root = str(tmp_path)
    _run(root, "ses_one", "2026-06-01T10:00:00", "/repo", [_finding("A")])
    upd = latest_update(root)
    assert upd["has_prev"] is False and len(upd["new"]) == 1


def test_dashboard_renders_ledger_tab_and_status_badges():
    ledger = [
        {"signature": "s1", "summary": "Save broken", "severity": "high",
         "suspected_area": "App.jsx:10", "status": "open", "occurrences": 2, "sessions": ["a", "b"]},
        {"signature": "s2", "summary": "Console err", "severity": "critical",
         "suspected_area": "x.js:1", "status": "verified", "occurrences": 1, "sessions": ["a"]},
    ]
    update = {"has_prev": True, "verified": [{"summary": "Console err"}],
              "new": [], "still_open": [{"summary": "Save broken"}]}
    stats = {"n_sessions": 2, "findings_total": 3, "by_severity": {}, "pass_rate": None}
    html = render_index([], stats, [], ledger=ledger, update=update)
    assert "Bug Ledger" in html and "tab-ledger" in html and "showTab" in html
    assert "st-open" in html and "st-verified" in html               # status badges
    assert "fixed since last run" in html                            # update panel
    assert "tab-badge" in html                                       # open-count badge on the tab
