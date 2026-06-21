"""Pure tests for the interactive replay player (slider + error timeline + overlays)."""
from __future__ import annotations

from inspector.replay import _build_html

_SESS = {"id": "ses_x", "surface": "android", "goal": "test", "state": "torn_down"}
_FRAMES = ["frame_0000.png", "frame_0001.png"]
_FINDINGS = [{
    "summary": "Save did nothing", "severity": "high", "confidence": "medium",
    "expected": "toast", "actual": "none", "repro": ["click Save"],
    "screenshot_refs": ["frame_0001.png"], "bbox": [0.1, 0.2, 0.3, 0.25],
}]
_ACTIONS = [{"seq": 0, "type": "click", "target_id": 2, "changed": False,
             "screenshot_before": "frame_0000.png", "screenshot_after": "frame_0001.png",
             "coords": [120, 60], "logs": []}]


def test_player_has_slider_timeline_and_clickable_findings():
    html = _build_html(_SESS, _FRAMES, _ACTIONS, _FINDINGS)
    assert "Save did nothing" in html
    assert "setFrame('frame_0001.png')" in html        # finding jumps to its frame
    assert "\U0001f4cd frame 2" in html                 # 📍 links WHICH frame it surfaced in
    assert "id='slider'" in html and "type='range'" in html   # the scrubber
    assert "id='track'" in html                         # the error timeline
    assert "id='pop'" in html                           # the popup container
    assert "[0.1, 0.2, 0.3, 0.25]" in html              # bbox embedded for the overlay
    assert "[120, 60]" in html                          # click coords → cursor overlay


def test_finding_without_location_is_not_clickable():
    findings = [{"summary": "logcat error", "severity": "medium", "confidence": "high",
                 "screenshot_refs": [], "bbox": []}]
    html = _build_html(_SESS, _FRAMES, _ACTIONS, findings)
    assert "logcat error" in html
    assert "setFrame('" not in html        # no frame ref → no jump link, no timeline marker
    assert "\U0001f4cd frame" not in html


def test_player_safe_without_frames():
    html = _build_html(_SESS, [], [], [])
    assert "id='slider'" not in html and "</html>" in html


def test_player_uses_shared_theme():
    html = _build_html(_SESS, _FRAMES, _ACTIONS, _FINDINGS)
    assert "Playfair+Display" in html and "--green:#15C78D" in html


def test_replay_finding_has_fix_with_devin_button():
    html = _build_html(_SESS, _FRAMES, _ACTIONS, _FINDINGS)
    assert "Fix with Devin" in html                 # every surfaced finding can launch Devin
    assert "devinFix(event" in html and "api/devin-fix" in html


def test_replay_has_back_link_to_dashboard():
    html = _build_html(_SESS, _FRAMES, _ACTIONS, _FINDINGS)
    assert "href='../dashboard.html'" in html and "All runs" in html
    # present even on an empty (no-frames) replay so navigation never dead-ends
    assert "href='../dashboard.html'" in _build_html(_SESS, [], [], [])
