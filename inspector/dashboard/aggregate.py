"""Pure aggregation over the on-disk trace tree (`~/.inspector/sessions/`).

Reads what the TraceRecorder already writes (docs/06) — session.json, run.json,
findings/, actions.jsonl, frames/ — and rolls every run up into summaries, stats,
recurring-bug groups, and the fix-loop context the host agent acts on. No new
capture; pure functions over the filesystem, unit-testable against a tmp tree.
"""

from __future__ import annotations

import json
import os
import re

_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_STATUSES = {"open", "fixed", "verified", "dismissed"}


# --- low-level readers -------------------------------------------------------

def _read_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception:
        pass
    return rows


def _count_lines(path: str) -> int:
    try:
        with open(path) as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _load_findings(session_dir: str) -> list[dict]:
    d = os.path.join(session_dir, "findings")
    out: list[dict] = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith(".json"):
                f = _read_json(os.path.join(d, name))
                if f:
                    out.append(f)
    return out


# --- summaries + stats -------------------------------------------------------

def session_summary(trace_root: str, sid: str) -> dict | None:
    """One row for the dashboard run list. None if `sid` has no session.json."""
    sdir = os.path.join(trace_root, sid)
    sess = _read_json(os.path.join(sdir, "session.json"))
    if not sess:
        return None
    run = _read_json(os.path.join(sdir, "run.json"))
    findings = _load_findings(sdir)

    by_sev = {k: 0 for k in _SEV_ORDER}
    by_status: dict[str, int] = {}
    for f in findings:
        sev = (f.get("severity") or "low").lower()
        by_sev[sev] = by_sev.get(sev, 0) + 1
        st = (f.get("status") or "open").lower()
        by_status[st] = by_status.get(st, 0) + 1

    frames_dir = os.path.join(sdir, "frames")
    n_frames = len(os.listdir(frames_dir)) if os.path.isdir(frames_dir) else 0
    has_replay = os.path.exists(os.path.join(sdir, "index.html"))
    has_video = os.path.exists(os.path.join(sdir, "replay.mp4")) or os.path.exists(
        os.path.join(sdir, "replay.gif")
    )
    return {
        "id": sess.get("id", sid),
        "alias": sess.get("alias"),
        "surface": sess.get("surface", ""),
        "goal": sess.get("goal", ""),
        "state": sess.get("state", ""),
        "repo_path": sess.get("repo_path", ""),
        "created_at": sess.get("created_at", ""),
        "ended_at": sess.get("ended_at"),
        "passed": run.get("passed") if run else None,
        "duration_ms": run.get("duration_ms", 0) if run else 0,
        "iterations": run.get("iterations", 0) if run else 0,
        "findings_total": len(findings),
        "by_severity": by_sev,
        "by_status": by_status,
        "n_actions": _count_lines(os.path.join(sdir, "actions.jsonl")),
        "n_frames": n_frames,
        "has_replay": has_replay,
        "has_video": has_video,
        "replay_path": f"{sess.get('id', sid)}/index.html" if has_replay else None,
    }


def scan_sessions(trace_root: str) -> list[dict]:
    """Every session under `trace_root`, newest first."""
    if not os.path.isdir(trace_root):
        return []
    out: list[dict] = []
    for name in sorted(os.listdir(trace_root)):
        if not os.path.isdir(os.path.join(trace_root, name)):
            continue
        summary = session_summary(trace_root, name)
        if summary:
            out.append(summary)
    out.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return out


def aggregate_stats(summaries: list[dict]) -> dict:
    """Cross-session totals for the dashboard header."""
    by_sev = {k: 0 for k in _SEV_ORDER}
    by_surface: dict[str, int] = {}
    passed = failed = unknown = findings_total = 0
    for s in summaries:
        for k, v in s["by_severity"].items():
            by_sev[k] = by_sev.get(k, 0) + v
        by_surface[s["surface"]] = by_surface.get(s["surface"], 0) + 1
        findings_total += s["findings_total"]
        if s["passed"] is True:
            passed += 1
        elif s["passed"] is False:
            failed += 1
        else:
            unknown += 1
    decided = passed + failed
    return {
        "n_sessions": len(summaries),
        "findings_total": findings_total,
        "by_severity": by_sev,
        "by_surface": by_surface,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "pass_rate": round(100 * passed / decided, 1) if decided else None,
    }


# --- recurring bugs across sessions -----------------------------------------

def collect_all_findings(trace_root: str) -> list[dict]:
    """Every finding across every session, tagged with its session id + surface."""
    out: list[dict] = []
    for s in scan_sessions(trace_root):
        for f in _load_findings(os.path.join(trace_root, s["id"])):
            f = dict(f)
            f["_session_id"] = s["id"]
            f["_surface"] = s["surface"]
            out.append(f)
    return out


def finding_signature(finding: dict) -> str:
    """Stable key collapsing volatile numbers — groups the 'same' bug across runs."""
    summary = re.sub(r"\d+", "#", finding.get("summary", ""))
    sev = (finding.get("severity") or "").lower()
    return f"{sev}|{finding.get('suspected_area', '')}|{summary[:120]}"


def _brief(f: dict) -> dict:
    return {
        "summary": f.get("summary", ""),
        "severity": (f.get("severity") or "low").lower(),
        "suspected_area": f.get("suspected_area", ""),
    }


def _session_signatures(trace_root: str, sid: str) -> dict[str, dict]:
    """{finding_signature -> finding} for one session."""
    return {finding_signature(f): f for f in _load_findings(os.path.join(trace_root, sid))}


_STATUS_ORDER = {"open": 0, "fixing": 1, "fixed": 2, "verified": 3, "dismissed": 4}


def bug_ledger(trace_root: str) -> list[dict]:
    """Every unique issue (by signature, per repo) with its CURRENT fix status.

    Status is evidence-based across runs: an issue present in the repo's latest run is
    `open`; one that appeared in an earlier run but is GONE from the latest run is
    `verified` (fixed — it no longer reproduces). A finding explicitly marked
    `dismissed` (via update_finding_status) stays dismissed. This is how the dashboard
    answers "was it ever fixed?" without trusting a manual flag alone.
    """
    runs = scan_sessions(trace_root)  # newest first
    sigs_by_sid = {s["id"]: _session_signatures(trace_root, s["id"]) for s in runs}

    by_repo: dict[str, list[dict]] = {}
    for s in runs:  # newest first preserved within each repo
        by_repo.setdefault(s["repo_path"], []).append(s)

    ledger: list[dict] = []
    for repo, repo_runs in by_repo.items():
        latest_sigs = sigs_by_sid[repo_runs[0]["id"]]
        groups: dict[str, dict] = {}
        for s in repo_runs:  # newest → oldest
            for sig, f in sigs_by_sid[s["id"]].items():
                g = groups.setdefault(sig, {
                    "signature": sig, "summary": f.get("summary", ""),
                    "severity": (f.get("severity") or "low").lower(),
                    "suspected_area": f.get("suspected_area", ""),
                    "repo_path": repo, "sessions": [], "manual": None,
                    "devin_url": None, "pr_url": None,
                })
                g["sessions"].append(s["id"])
                st = (f.get("status") or "open").lower()
                if g["manual"] is None and st in ("dismissed", "fixing", "fixed", "verified"):
                    g["manual"] = st
                if not g["devin_url"] and f.get("devin_url"):
                    g["devin_url"] = f["devin_url"]
                if not g["pr_url"] and f.get("pr_url"):
                    g["pr_url"] = f["pr_url"]
        for sig, g in groups.items():
            present = sig in latest_sigs
            if g["manual"] == "dismissed":
                status = "dismissed"
            elif present:
                status = "fixing" if g["manual"] == "fixing" else "open"
            else:
                status = "verified"  # seen before, absent from the latest run → fixed
            g.update({
                "status": status,
                "present_latest": present,
                "occurrences": len(g["sessions"]),
                "latest_session": repo_runs[0]["id"],
            })
            g.pop("manual", None)
            ledger.append(g)

    ledger.sort(key=lambda g: (_STATUS_ORDER.get(g["status"], 9),
                               _SEV_ORDER.get(g["severity"], 9)))
    return ledger


def findings_for_signature(trace_root: str, signature: str) -> list[dict]:
    """Every finding file matching `signature`, newest run first, with its repo/session."""
    out: list[dict] = []
    for s in scan_sessions(trace_root):  # newest first
        fdir = os.path.join(trace_root, s["id"], "findings")
        if not os.path.isdir(fdir):
            continue
        for name in sorted(os.listdir(fdir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(fdir, name)
            data = _read_json(path)
            if data and finding_signature(data) == signature:
                out.append({"path": path, "data": data, "repo_path": s["repo_path"],
                            "session_id": s["id"], "created_at": s["created_at"]})
    return out


def signature_for_finding(trace_root: str, session_id: str, finding_id: str) -> str | None:
    """The bug signature for one specific finding (session_id + finding_id).

    Lets any surfaced finding — a replay card, not just a ledger row — be handed to
    Devin: resolve it to its signature, then fix_with_devin patches every occurrence.
    """
    from ..paths import valid_id
    if not valid_id(session_id):
        return None
    fdir = os.path.join(trace_root, session_id, "findings")
    if not os.path.isdir(fdir):
        return None
    for name in os.listdir(fdir):
        data = _read_json(os.path.join(fdir, name))
        if data.get("id") == finding_id:
            return finding_signature(data)
    return None


def patch_finding(path: str, fields: dict) -> bool:
    """Merge `fields` into a finding file on disk (used by the Devin fix loop)."""
    data = _read_json(path)
    if not data:
        return False
    data.update(fields)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return True


def latest_update(trace_root: str) -> dict:
    """What changed in the most recent run vs the prior run of the SAME repo.

    The 'update' the dashboard surfaces: issues newly `verified` (gone since last run),
    `new` (appeared this run), and `still_open` (persisted). Empty when there's no run.
    """
    runs = scan_sessions(trace_root)  # newest first
    if not runs:
        return {}
    latest = runs[0]
    repo = latest["repo_path"]
    repo_runs = [s for s in runs if s["repo_path"] == repo]  # newest first
    cur = _session_signatures(trace_root, latest["id"])
    prev = _session_signatures(trace_root, repo_runs[1]["id"]) if len(repo_runs) > 1 else {}
    cur_set, prev_set = set(cur), set(prev)
    return {
        "repo_path": repo,
        "run_id": latest["id"],
        "alias": latest.get("alias"),
        "has_prev": len(repo_runs) > 1,
        "verified": [_brief(prev[s]) for s in (prev_set - cur_set)],   # gone → fixed
        "new": [_brief(cur[s]) for s in (cur_set - prev_set)],          # appeared this run
        "still_open": [_brief(cur[s]) for s in (cur_set & prev_set)],   # persisted
    }


def recurring_findings(trace_root: str, min_sessions: int = 2) -> list[dict]:
    """Bugs that show up in `min_sessions`+ distinct sessions — likely real, not flaky."""
    groups: dict[str, dict] = {}
    for f in collect_all_findings(trace_root):
        sig = finding_signature(f)
        g = groups.setdefault(sig, {
            "signature": sig,
            "summary": f.get("summary", ""),
            "severity": (f.get("severity") or "low").lower(),
            "suspected_area": f.get("suspected_area", ""),
            "count": 0,
            "session_ids": [],
        })
        g["count"] += 1
        if f["_session_id"] not in g["session_ids"]:
            g["session_ids"].append(f["_session_id"])
    rec = [g for g in groups.values() if len(g["session_ids"]) >= min_sessions]
    rec.sort(key=lambda g: (_SEV_ORDER.get(g["severity"], 9), -g["count"]))
    return rec


# --- detail + fix loop -------------------------------------------------------

def fix_prompt(finding: dict, session: dict | None) -> str:
    """A ready-to-paste prompt for the coding agent to fix one finding."""
    sess = session or {}
    repro = finding.get("repro") or []
    steps = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(repro)) or "  (no recorded steps)"
    logs = finding.get("logs") or []
    evidence = ("\nEvidence:\n  " + "\n  ".join(logs[:6]) + "\n") if logs else ""
    return (
        f"Fix this bug Inspector found in {sess.get('repo_path') or 'the app'} "
        f"({sess.get('surface', '')}).\n\n"
        f"Severity: {finding.get('severity', '?')} ({finding.get('confidence', '?')} confidence)\n"
        f"What's wrong: {finding.get('summary', '')}\n"
        f"Expected: {finding.get('expected') or '(n/a)'}\n"
        f"Actual: {finding.get('actual') or '(n/a)'}\n"
        f"Suspected location: {finding.get('suspected_area') or '(unknown)'}\n"
        f"Reproduction:\n{steps}\n"
        f"{evidence}"
        f"\nAfter fixing, re-run Inspector to confirm finding {finding.get('id', '')} "
        f"no longer reproduces, then mark it verified."
    )


def load_session_detail(trace_root: str, sid: str) -> dict:
    """Full detail for one session: meta + findings (with fix prompts) + timeline."""
    from ..paths import valid_id
    if not valid_id(sid):
        return {"session": None, "run": None, "plan": None,
                "findings": [], "actions": [], "frames": []}
    sdir = os.path.join(trace_root, sid)
    sess = _read_json(os.path.join(sdir, "session.json"))
    findings = _load_findings(sdir)
    for f in findings:
        f["fix_prompt"] = fix_prompt(f, sess)
    frames_dir = os.path.join(sdir, "frames")
    frames = sorted(os.listdir(frames_dir)) if os.path.isdir(frames_dir) else []
    return {
        "session": sess,
        "run": _read_json(os.path.join(sdir, "run.json")),
        "plan": _read_json(os.path.join(sdir, "plan.json")),
        "findings": findings,
        "actions": _read_jsonl(os.path.join(sdir, "actions.jsonl")),
        "frames": frames,
    }


def update_finding_status(trace_root: str, sid: str, finding_id: str, status: str) -> dict:
    """Write a finding's fix-loop status back to disk (open|fixed|verified|dismissed).

    Works on any session on disk (live or long-finished) — the fix loop the
    dashboard surfaces and the host agent drives.
    """
    if status not in _STATUSES:
        return {"error": f"status must be one of {sorted(_STATUSES)}"}
    from ..paths import valid_id
    if not valid_id(sid):
        return {"error": f"invalid session id {sid!r}"}
    fdir = os.path.join(trace_root, sid, "findings")
    if os.path.isdir(fdir):
        for name in os.listdir(fdir):
            path = os.path.join(fdir, name)
            data = _read_json(path)
            if data.get("id") == finding_id:
                data["status"] = status
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
                return {"finding_id": finding_id, "status": status}
    return {"error": f"unknown finding {finding_id!r} in session {sid!r}"}
