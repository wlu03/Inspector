"""Close the loop: after a fix lands, re-run a finding's repro against the new build
and report whether the bug is gone.

The recorded actions (actions.jsonl) ARE a deterministic re-run script — replay them
by coordinate on a freshly-launched session, then check whether the finding's signature
reappears. If it's gone, mark the finding fixed in the trace.
"""
from __future__ import annotations

import json
import os
import re

from .autopilot import collect_findings


def load_actions(session_dir: str) -> list[dict]:
    """Recorded actions from a prior session's actions.jsonl (the re-run script)."""
    path = os.path.join(session_dir, "actions.jsonl")
    out: list[dict] = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
    return out


def replay_actions(session, actions: list[dict]) -> int:
    """Re-drive recorded actions by coordinate against a fresh session. Returns the
    number of actions replayed (skips ones with no usable coordinate)."""
    from .models import ActionType
    n = 0
    for a in actions:
        try:
            t = ActionType(a.get("type", "wait"))
        except ValueError:
            continue
        coords = a.get("coords")
        if t in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.DRAG) and not coords:
            continue  # can't replay a click with no recorded coordinate
        try:
            session.act(t, coords=coords, text=a.get("text"), key=a.get("key"))
            n += 1
        except Exception:
            continue
    return n


def _norm_summary(s: str) -> str:
    return re.sub(r"\d+", "#", s or "").strip()[:120]


def signature_present(findings: list[dict], target_summary: str) -> bool:
    """Did a finding matching the target (digit-normalized summary) resurface?"""
    target = _norm_summary(target_summary)
    return any(_norm_summary(f.get("summary", "")) == target for f in findings)


def verify_fix(config, repo_path: str, prior_session_dir: str, target_summary: str,
               surface=None) -> dict:
    """Launch the (post-fix) app, replay the prior repro, and report fixed/still-present."""
    from .session import SessionManager
    mgr = SessionManager(config)
    session = mgr.create(repo_path, surface, goal=f"re-verify: {target_summary[:60]}")
    sid = session.record.id
    try:
        if not session.launch():
            return {"status": "error", "detail": "app did not become ready", "session_id": sid}
        replayed = replay_actions(session, load_actions(prior_session_dir))
        new = collect_findings(session)
        present = signature_present(new, target_summary)
        return {
            "status": "still_present" if present else "fixed",
            "reproduced": present,
            "actions_replayed": replayed,
            "new_findings": len(new),
            "session_id": sid,
        }
    finally:
        mgr.stop(sid)


def mark_fixed(session_dir: str, target_summary: str, fixed: bool) -> int:
    """Stamp matching findings in a trace's findings/ as fixed|still-open. Returns count."""
    fdir = os.path.join(session_dir, "findings")
    if not os.path.isdir(fdir):
        return 0
    target = _norm_summary(target_summary)
    n = 0
    for name in os.listdir(fdir):
        if not name.endswith(".json"):
            continue
        path = os.path.join(fdir, name)
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        if _norm_summary(d.get("summary", "")) == target:
            d["status"] = "fixed" if fixed else "open"
            with open(path, "w") as f:
                json.dump(d, f, indent=2)
            n += 1
    return n
