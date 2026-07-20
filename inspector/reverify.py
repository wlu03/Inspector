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


def _find_by_label(elements, locator: str):
    """Re-find an element by its semantic label (exact, then contains). None if absent."""
    if not locator:
        return None
    t = locator.strip().lower()
    for e in elements:
        if (e.label or "").strip().lower() == t:
            return e
    for e in elements:
        if t and t in (e.label or "").lower():
            return e
    return None


def replay_spec(session, spec) -> tuple[int, int]:
    """Replay a ReproSpec by SEMANTIC locator (re-find each element by label from the
    live observation), not raw coordinates. Returns (steps_completed, steps_total);
    stops early when a step's element can't be found (the scenario diverged)."""
    from .models import ActionType

    steps = list(getattr(spec, "steps", []) or [])
    valid = {t.value for t in ActionType}
    done = 0
    for step in steps:
        at = ActionType(step.action) if step.action in valid else ActionType.WAIT
        try:
            if at in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
                session.observe()
                el = _find_by_label(session.last_elements, step.locator)
                if el is None:
                    break  # scenario diverged -> not fully reached
                session.act(at, target_id=el.id)
            elif at == ActionType.TYPE:
                session.act(at, text=step.text)
            elif at == ActionType.KEY:
                session.act(at, key=step.key)
            done += 1
        except Exception:
            break
    return done, len(steps)


def _eval_oracle(session, oracle) -> str | None:
    """Evaluate a ReproSpec oracle (the CORRECT behavior). pass -> fixed, fail ->
    still_present, inconclusive -> not_run. None when there is no oracle."""
    if not oracle:
        return None
    from .assertions import evaluate_assertions, summarize
    labels = {a.on for a in oracle if getattr(a, "on", "")}
    results = evaluate_assertions(oracle, **session.observation_context(labels))
    overall = summarize(results)["overall"]
    return {"pass": "fixed", "fail": "still_present"}.get(overall, "not_run")


def verify_fix_spec(config, repo_path: str, spec, target_summary: str, surface=None) -> dict:
    """Re-verify using the finding's ReproSpec: launch the current build, replay the
    scenario by semantic locator, and judge by the explicit oracle (falling back to
    signature absence). Reports not_run when the scenario can't be reproduced."""
    from .session import SessionManager

    mgr = SessionManager(config)
    session = mgr.create(repo_path, surface, goal=f"re-verify: {target_summary[:60]}")
    sid = session.record.id
    try:
        if not session.launch():
            return {"status": "not_run", "detail": "app did not become ready",
                    "session_id": sid}
        done, total = replay_spec(session, spec)
        if total and done < total:
            return {"status": "not_run",
                    "detail": f"scenario diverged at step {done + 1}/{total}",
                    "steps_replayed": done, "steps_total": total, "session_id": sid}
        oracle_status = _eval_oracle(session, getattr(spec, "oracle", None))
        if oracle_status is not None:
            return {"status": oracle_status, "oracle": True,
                    "steps_replayed": done, "steps_total": total, "session_id": sid}
        new = collect_findings(session)
        present = signature_present(new, target_summary)
        return {"status": "still_present" if present else "fixed", "reproduced": present,
                "steps_replayed": done, "steps_total": total, "new_findings": len(new),
                "session_id": sid}
    finally:
        mgr.stop(sid)
