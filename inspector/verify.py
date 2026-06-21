"""Adversarial verification: try to REFUTE each judgment-based finding before it's
reported, so speculative false-positives don't ship as bugs.

Deterministic log-tap findings (a real crash/exception line) are facts — kept as-is.
Findings born from the driver's visual judgment or the missing-element oracle are
re-examined by the brain with a skeptical prompt; refuted ones are marked dismissed
in the trace (kept for audit, not deleted) and dropped from the confirmed count.
"""
from __future__ import annotations

import json
import os


def verify_findings(session, driver) -> dict:
    """Refute judgment findings via the driver's brain. Returns a summary dict."""
    verifier = getattr(driver, "verify_finding", None)
    fdir = session.trace.findings_dir
    if verifier is None or not os.path.isdir(fdir):
        return {"verified": 0, "dismissed": 0, "trusted": 0}

    verified = dismissed = trusted = 0
    for name in sorted(os.listdir(fdir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(fdir, name)
        try:
            with open(path) as f:
                finding = json.load(f)
        except Exception:
            continue

        # a deterministic log-tap finding carries the raw log line — it's a fact, trust it
        if finding.get("logs"):
            trusted += 1
            continue

        shot = _load_frame(session, finding.get("screenshot_refs"))
        try:
            verdict = verifier(finding, shot) or {}
        except Exception:
            verified += 1  # a verifier hiccup shouldn't silently drop a finding
            continue

        if verdict.get("confirmed"):
            finding["status"] = "verified"
            verified += 1
        else:
            finding["status"] = "dismissed"
            finding["confidence"] = "low"
            finding["actual"] = (finding.get("actual") or "") + \
                f"  [refuted: {verdict.get('reason', '')}]"
            dismissed += 1
        _save(path, finding)

    return {"verified": verified, "dismissed": dismissed, "trusted": trusted}


def confirmed_findings(session) -> list[dict]:
    """Findings that survived verification (not dismissed) — the report-worthy set."""
    out: list[dict] = []
    fdir = session.trace.findings_dir
    if os.path.isdir(fdir):
        for name in sorted(os.listdir(fdir)):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(fdir, name)) as f:
                        d = json.load(f)
                    if d.get("status") != "dismissed":
                        out.append(d)
                except Exception:
                    continue
    return out


def _load_frame(session, refs) -> bytes:
    if not refs:
        return b""
    try:
        with open(os.path.join(session.trace.frames_dir, refs[0]), "rb") as f:
            return f.read()
    except Exception:
        return b""


def _save(path: str, finding: dict) -> None:
    try:
        with open(path, "w") as f:
            json.dump(finding, f, indent=2)
    except Exception:
        pass
