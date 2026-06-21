"""Test the grouped parallel-run report renderer."""
from __future__ import annotations

import os

from inspector.parallel_report import write_parallel_report


def test_grouped_report_links_each_agent_and_findings(tmp_path):
    for sid in ("ses_a", "ses_b"):
        fdir = tmp_path / sid / "frames"
        fdir.mkdir(parents=True)
        (fdir / "frame_0000.png").write_bytes(b"\x89PNG")
        (fdir / "frame_0001.png").write_bytes(b"\x89PNG")
    parts = [
        {"part": "Settings", "session_id": "ses_a", "status": "ok", "steps": 3, "findings_total": 1},
        {"part": "Cart", "session_id": "ses_b", "status": "error", "steps": 0, "findings_total": 0},
    ]
    merged = [{"severity": "medium", "summary": "Cart total wrong", "suspected_area": "(brain)"}]
    plan = [{"name": "Settings", "goal": "test settings"}, {"name": "Cart", "goal": "test cart"}]

    path = write_parallel_report(str(tmp_path), plan, parts, merged)
    assert os.path.exists(path)
    page = open(path).read()
    # each agent links to its own replay + its latest frame as a thumbnail
    assert "../ses_a/index.html" in page
    assert "../ses_a/frames/frame_0001.png" in page   # last frame, not first
    assert "../ses_b/index.html" in page
    # plan, statuses, and merged findings all surface in the one page
    assert "Settings" in page and "Cart" in page
    assert "error" in page and "ok" in page
    assert "Cart total wrong" in page


def test_report_handles_missing_frames(tmp_path):
    parts = [{"part": "About", "session_id": "ses_x", "status": "ok", "steps": 1, "findings_total": 0}]
    path = write_parallel_report(str(tmp_path), [], parts, [])
    page = open(path).read()
    assert "no frames" in page and "No findings" in page
