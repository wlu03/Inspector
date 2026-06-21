"""Pure tests for the interactive replay HTML (metadata + clickable bug markers)."""
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
             "screenshot_before": "frame_0000.png", "screenshot_after": "frame_0001.png", "logs": []}]


def test_html_embeds_metadata_and_clickable_findings():
    html = _build_html(_SESS, _FRAMES, _ACTIONS, _FINDINGS)
    assert "Annotator" in html
    assert "Save did nothing" in html
    assert "setFrame('frame_0001.png')" in html        # finding jumps to its frame
    assert "\U0001f4cd" in html                         # 📍 located-finding pin
    assert "exportMeta" in html                         # export button + annotator JS
    assert "[0.1, 0.2, 0.3, 0.25]" in html              # bbox embedded in metadata
    assert "id='meta'" in html                          # live metadata block


def test_html_handles_finding_without_location():
    findings = [{"summary": "logcat error", "severity": "medium", "confidence": "high",
                 "screenshot_refs": [], "bbox": []}]
    html = _build_html(_SESS, _FRAMES, _ACTIONS, findings)
    assert "logcat error" in html
    # no frame ref → the finding isn't clickable and gets no auto-marker
    assert "setFrame('" not in html


def test_html_safe_without_frames():
    html = _build_html(_SESS, [], [], [])
    assert "Annotator" not in html and "</html>" in html
