"""Tests for the static dashboard aggregator + the replay cursor/intent overlay."""
from __future__ import annotations

import json
import os

from inspector.dashboard.aggregate import (
    aggregate_stats,
    bug_ledger,
    fix_prompt,
    latest_update,
    load_session_detail,
    recurring_findings,
    scan_sessions,
    session_summary,
    update_finding_status,
)
from inspector.dashboard.build import build_dashboard
from inspector.dashboard.render import render_index
from inspector.theme import head_style


def _finding(fid, summary, severity="high", status="open", area="App.jsx:10"):
    return {
        "id": fid, "summary": summary, "severity": severity, "confidence": "high",
        "status": status, "repro": ["click #1", "type 'x'"], "expected": "works",
        "actual": "broke", "suspected_area": area, "logs": ["TypeError: boom"],
    }


def _mk_session(root, sid, created, surface, passed, findings, n_actions=0, frames=None):
    sdir = os.path.join(root, sid)
    os.makedirs(os.path.join(sdir, "findings"), exist_ok=True)
    with open(os.path.join(sdir, "session.json"), "w") as f:
        json.dump({"id": sid, "surface": surface, "goal": f"test {surface}",
                   "state": "torn_down", "repo_path": f"/repo/{surface}",
                   "created_at": created, "ended_at": created}, f)
    with open(os.path.join(sdir, "run.json"), "w") as f:
        json.dump({"passed": passed, "duration_ms": 1000, "iterations": n_actions}, f)
    for fd in findings:
        with open(os.path.join(sdir, "findings", f"{fd['id']}.json"), "w") as f:
            json.dump(fd, f)
    if n_actions:
        with open(os.path.join(sdir, "actions.jsonl"), "w") as f:
            for i in range(n_actions):
                f.write(json.dumps({
                    "seq": i, "type": "click", "target_id": i, "changed": True,
                    "screenshot_before": f"frame_{2*i:04d}.png",
                    "screenshot_after": f"frame_{2*i+1:04d}.png",
                    "coords": [10 + i, 20 + i],
                }) + "\n")
    if frames:
        fdir = os.path.join(sdir, "frames")
        os.makedirs(fdir, exist_ok=True)
        from PIL import Image
        for name in frames:
            Image.new("RGB", (40, 30), (20, 20, 20)).save(os.path.join(fdir, name))
    return sdir


def _tree(root):
    # recurring bug (same summary+area+severity) appears in A and C → recurring
    bug = _finding("fnd_a", "Save button does nothing", "high")
    _mk_session(root, "ses_a", "2026-06-01T10:00:00", "web", False,
                [bug, _finding("fnd_a2", "Console error x99", "critical")], n_actions=2)
    _mk_session(root, "ses_b", "2026-06-03T10:00:00", "android", True, [])
    _mk_session(root, "ses_c", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_c", "Save button does nothing", "high")])


# --- aggregate ---------------------------------------------------------------

def test_scan_sessions_newest_first(tmp_path):
    _tree(str(tmp_path))
    sessions = scan_sessions(str(tmp_path))
    assert [s["id"] for s in sessions] == ["ses_b", "ses_c", "ses_a"]  # by created_at desc


def test_session_summary_counts(tmp_path):
    _tree(str(tmp_path))
    s = session_summary(str(tmp_path), "ses_a")
    assert s["findings_total"] == 2
    assert s["by_severity"]["high"] == 1 and s["by_severity"]["critical"] == 1
    assert s["passed"] is False
    assert s["n_actions"] == 2


def test_aggregate_stats(tmp_path):
    _tree(str(tmp_path))
    stats = aggregate_stats(scan_sessions(str(tmp_path)))
    assert stats["n_sessions"] == 3
    assert stats["findings_total"] == 3
    assert stats["passed"] == 1 and stats["failed"] == 2
    assert stats["pass_rate"] == round(100 * 1 / 3, 1)


def test_recurring_findings_groups_across_sessions(tmp_path):
    _tree(str(tmp_path))
    rec = recurring_findings(str(tmp_path))
    assert len(rec) == 1
    assert rec[0]["summary"] == "Save button does nothing"
    assert set(rec[0]["session_ids"]) == {"ses_a", "ses_c"}


def test_fix_prompt_has_the_actionable_fields(tmp_path):
    prompt = fix_prompt(_finding("fnd_x", "Broken thing"), {"repo_path": "/r", "surface": "web"})
    assert "Broken thing" in prompt and "App.jsx:10" in prompt
    assert "Reproduction:" in prompt and "click #1" in prompt
    assert "/r" in prompt and "verified" in prompt


def test_update_finding_status_writes_back(tmp_path):
    _tree(str(tmp_path))
    assert update_finding_status(str(tmp_path), "ses_a", "fnd_a", "fixed") == {
        "finding_id": "fnd_a", "status": "fixed"}
    detail = load_session_detail(str(tmp_path), "ses_a")
    statuses = {f["id"]: f["status"] for f in detail["findings"]}
    assert statuses["fnd_a"] == "fixed"


def test_update_finding_status_rejects_bad_status_and_unknown(tmp_path):
    _tree(str(tmp_path))
    assert "error" in update_finding_status(str(tmp_path), "ses_a", "fnd_a", "bogus")
    assert "error" in update_finding_status(str(tmp_path), "ses_a", "nope", "fixed")


def test_load_session_detail_attaches_fix_prompts(tmp_path):
    _tree(str(tmp_path))
    detail = load_session_detail(str(tmp_path), "ses_a")
    assert len(detail["findings"]) == 2
    assert all(f.get("fix_prompt") for f in detail["findings"])
    assert len(detail["actions"]) == 2


# --- bug ledger honesty ------------------------------------------------------
# The ledger is the screen someone reads to decide "am I done?", so these tests pin the
# one property that matters: green means evidence, never just "the run didn't mention it".

def _by_summary(root):
    return {g["summary"]: g for g in bug_ledger(str(root))}


def test_ledger_short_latest_run_does_not_verify_a_missing_bug(tmp_path):
    # a 10-action run found the bug; the latest run poked at the app for 2 actions and
    # found something else entirely — it never went looking, so it proves nothing.
    _mk_session(tmp_path, "ses_long", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Save button does nothing")], n_actions=10)
    _mk_session(tmp_path, "ses_short", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_b", "Header misaligned")], n_actions=2)
    g = _by_summary(tmp_path)
    assert g["Save button does nothing"]["status"] == "not_run"
    assert "2 actions" in g["Save button does nothing"]["evidence"]
    assert g["Header misaligned"]["status"] == "open"       # it did reproduce


def test_ledger_latest_run_with_no_findings_is_not_run(tmp_path):
    _mk_session(tmp_path, "ses_a", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Save button does nothing")], n_actions=6)
    _mk_session(tmp_path, "ses_b", "2026-06-02T10:00:00", "web", True, [], n_actions=6)
    [g] = bug_ledger(str(tmp_path))
    assert g["status"] == "not_run"
    assert "no findings" in g["evidence"]


def test_ledger_comparable_run_that_misses_a_bug_reads_absent_not_verified(tmp_path):
    # the latest run did the same amount of work and the bug didn't come back. Suggestive
    # — but nobody signed it off, so it is `absent`, not green.
    _mk_session(tmp_path, "ses_a", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Save button does nothing"),
                 _finding("fnd_b", "Header misaligned")], n_actions=6)
    _mk_session(tmp_path, "ses_b", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_b2", "Header misaligned")], n_actions=6)
    g = _by_summary(tmp_path)
    assert g["Save button does nothing"]["status"] == "absent"
    assert g["Save button does nothing"]["status"] != "verified"
    assert "never signed off" in g["Save button does nothing"]["evidence"]
    assert g["Header misaligned"]["status"] == "open"


def test_ledger_verified_only_after_explicit_sign_off(tmp_path):
    _mk_session(tmp_path, "ses_a", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Save button does nothing")], n_actions=6)
    _mk_session(tmp_path, "ses_b", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_b", "Header misaligned")], n_actions=6)
    assert _by_summary(tmp_path)["Save button does nothing"]["status"] == "absent"
    update_finding_status(str(tmp_path), "ses_a", "fnd_a", "verified")
    g = _by_summary(tmp_path)["Save button does nothing"]
    assert g["status"] == "verified"
    assert "signed off" in g["evidence"]


def test_ledger_sign_off_on_the_latest_run_still_reads_verified(tmp_path):
    # signed off inside the only run there is: the sign-off is the evidence, and the
    # finding's presence is just the record it was signed off on.
    _mk_session(tmp_path, "ses_a", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Save button does nothing")], n_actions=6)
    assert bug_ledger(str(tmp_path))[0]["status"] == "open"
    update_finding_status(str(tmp_path), "ses_a", "fnd_a", "verified")
    [g] = bug_ledger(str(tmp_path))
    assert g["status"] == "verified" and "latest run" in g["evidence"]


def test_ledger_reproducing_again_overrides_an_old_sign_off(tmp_path):
    # signed off in the old run, back in the latest one → open. Evidence beats paperwork.
    _mk_session(tmp_path, "ses_a", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Save button does nothing", status="verified")], n_actions=6)
    _mk_session(tmp_path, "ses_b", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_b", "Save button does nothing")], n_actions=6)
    [g] = bug_ledger(str(tmp_path))
    assert g["status"] == "open" and "reproduced" in g["evidence"]


def test_ledger_sorts_open_then_unproven_then_verified(tmp_path):
    _mk_session(tmp_path, "ses_a", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Still broken"), _finding("fnd_b", "Quietly gone"),
                 _finding("fnd_c", "Actually checked")], n_actions=6)
    _mk_session(tmp_path, "ses_b", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_a2", "Still broken")], n_actions=6)
    update_finding_status(str(tmp_path), "ses_a", "fnd_c", "verified")
    assert [g["status"] for g in bug_ledger(str(tmp_path))] == ["open", "absent", "verified"]


def test_latest_update_splits_verified_from_merely_absent(tmp_path):
    _mk_session(tmp_path, "ses_old", "2026-06-01T10:00:00", "web", False,
                [_finding("fnd_a", "Checked and fixed"), _finding("fnd_b", "Just vanished")],
                n_actions=6)
    _mk_session(tmp_path, "ses_new", "2026-06-02T10:00:00", "web", False,
                [_finding("fnd_c", "Brand new bug")], n_actions=6)
    update_finding_status(str(tmp_path), "ses_old", "fnd_a", "verified")
    upd = latest_update(str(tmp_path))
    assert [x["summary"] for x in upd["verified"]] == ["Checked and fixed"]
    assert [x["summary"] for x in upd["absent"]] == ["Just vanished"]
    assert [x["summary"] for x in upd["new"]] == ["Brand new bug"]
    assert upd["still_open"] == []


# --- render + build ----------------------------------------------------------

def test_render_index_uses_theme_and_shows_runs(tmp_path):
    _tree(str(tmp_path))
    summaries = scan_sessions(str(tmp_path))
    htmlout = render_index(summaries, aggregate_stats(summaries), recurring_findings(str(tmp_path)))
    assert "Playfair+Display" in htmlout and "Geist" in htmlout       # landing fonts
    assert "#15C78D" in htmlout                                        # accent green
    assert "ses_a" in htmlout and "Recurring across runs" in htmlout
    assert "sev-critical" in htmlout
    assert "id='ses_a'" in htmlout and "highlightHash" in htmlout   # deep-link target + handler


def test_render_ledger_shows_unproven_statuses_with_their_evidence():
    ledger = [
        {"signature": "s1", "summary": "Save broken", "severity": "high", "status": "open",
         "evidence": "reproduced in the latest run ses_b", "occurrences": 2,
         "sessions": ["a", "b"]},
        {"signature": "s2", "summary": "Quietly gone", "severity": "high", "status": "absent",
         "evidence": "did not reappear in the latest run, never signed off",
         "occurrences": 1, "sessions": ["a"]},
        {"signature": "s3", "summary": "Never looked", "severity": "low", "status": "not_run",
         "evidence": "latest run recorded no findings at all", "occurrences": 1,
         "sessions": ["a"]},
    ]
    update = {"has_prev": True, "verified": [], "absent": [{"summary": "Quietly gone"}],
              "new": [], "still_open": [{"summary": "Save broken"}]}
    stats = {"n_sessions": 2, "findings_total": 3, "by_severity": {}, "pass_rate": None}
    htmlout = render_index([], stats, [], ledger=ledger, update=update)
    assert "st-absent" in htmlout and "st-not_run" in htmlout   # distinct status classes
    assert ">not run<" in htmlout                                # underscore humanised
    assert "never signed off" in htmlout                         # evidence is shown
    assert "gone, not verified" in htmlout                       # absent kept out of "fixed"
    assert ".st-absent{color:var(--sev-low)}" in htmlout         # distinct styling


def test_build_dashboard_writes_files_and_replays(tmp_path):
    root = str(tmp_path)
    _tree(root)
    # give ses_a frames so ensure_replays regenerates a per-session replay
    fdir = os.path.join(root, "ses_a", "frames")
    os.makedirs(fdir, exist_ok=True)
    from PIL import Image
    for i in range(4):
        Image.new("RGB", (40, 30), (20, 20, 20)).save(os.path.join(fdir, f"frame_{i:04d}.png"))

    path = build_dashboard(root)
    assert os.path.exists(path)
    assert os.path.exists(os.path.join(root, "dashboard.json"))
    assert os.path.exists(os.path.join(root, "ses_a", "index.html"))  # replay generated
    with open(path) as f:
        assert "ses_a" in f.read()


def test_head_style_bundles_tokens_and_fonts():
    css = head_style(".x{color:red}")
    assert "--green:#15C78D" in css and "Geist+Mono" in css and ".x{color:red}" in css


# --- replay overlay (cursor + click intent) ----------------------------------

def test_intent_describes_actions():
    from inspector.replay import _intent
    assert _intent({"type": "type", "text": "hi"}) == 'type "hi"'
    assert _intent({"type": "key", "key": "Escape"}) == "press Escape"
    assert _intent({"type": "click", "target_id": 3}) == "click #3"


def test_frame_overlays_maps_before_after(tmp_path):
    from inspector.replay import _frame_overlays
    root = str(tmp_path)
    _mk_session(root, "ses_v", "2026-06-01T10:00:00", "web", False, [], n_actions=1)
    names = ["frame_0000.png", "frame_0001.png", "frame_0002.png"]
    ov = _frame_overlays(os.path.join(root, "ses_v"), names)
    assert ov["frame_0000.png"]["cursor"] == (10, 20)        # before-shot has the click point
    assert "click #0" in ov["frame_0000.png"]["caption"]
    assert "changed" in ov["frame_0001.png"]["caption"]      # after-shot
    assert "observe" in ov["frame_0002.png"]["caption"]      # unreferenced frame
