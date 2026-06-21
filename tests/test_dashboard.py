"""Tests for the static dashboard aggregator + the replay cursor/intent overlay."""
from __future__ import annotations

import json
import os

from inspector.dashboard.aggregate import (
    aggregate_stats,
    fix_prompt,
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
