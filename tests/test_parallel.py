"""Test the fan-out verifier's orchestration + merge (no real sessions)."""
from __future__ import annotations

import inspector.parallel as P
from inspector.config import Config


def test_parallel_verify_runs_each_part_and_dedupes(monkeypatch):
    seen_parts = []

    def fake_verify_part(mgr, config, repo, part, surface, max_steps):
        seen_parts.append(part["name"])
        return {
            "part": part["name"], "status": "ok", "steps": 2, "findings_total": 1,
            "findings": [{"summary": part["bug"]}],
        }

    monkeypatch.setattr(P, "verify_part", fake_verify_part)
    res = P.parallel_verify(
        Config(), "/repo",
        parts=[
            {"name": "settings", "goal": "g", "bug": "Toggle desync"},
            {"name": "profile", "goal": "g", "bug": "toggle desync"},   # dupe (case)
            {"name": "about", "goal": "g", "bug": "Reset no-op"},
        ],
        max_workers=3,
    )
    assert res["agents"] == 3
    assert sorted(seen_parts) == ["about", "profile", "settings"]   # every part ran
    assert res["total_unique_findings"] == 2                        # the two desyncs merge
    assert {p["part"] for p in res["parts"]} == {"settings", "profile", "about"}
    # per-part results carry status/steps but not the raw findings blob
    assert all("findings" not in p for p in res["parts"])
