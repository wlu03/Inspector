"""Phase 0 orchestrator: MAP -> per-region deterministic lenses -> ranked FixItems.

Sequential on one session (the single CDP/idb transport is non-reentrant). Every
candidate is a MEASURED oracle violation, recorded as a Finding so the replay +
dashboard + eval light up for free. No verifier yet — the oracles are deterministic.
"""

from __future__ import annotations

from ..findings import build_finding
from ..models import Severity
from .capture import capture
from .lenses import LENSES
from .mapper import segment
from .models import Candidate

_SEV = {"low": Severity.LOW, "medium": Severity.MEDIUM, "high": Severity.HIGH, "critical": Severity.CRITICAL}


def _suggested_fix(c: Candidate) -> str:
    o = c.evidence.get("oracle", "")
    if c.lens == "logic_arithmetic" and "COUNTER_DELTA" in o:
        return (f"The increment handler for {c.issue.split(chr(39))[1] if chr(39) in c.issue else 'this control'} "
                f"applies the wrong step — change it to add {c.expected.split('==')[-1].strip()} "
                f"(observed {c.actual.split('==')[-1].strip()}).")
    if c.lens == "logic_arithmetic" and "RESET_TO" in o:
        return "The reset handler sets the wrong baseline — set the value to 0 instead of its current literal."
    if c.lens == "state_sync":
        return ("The toggle updates its label without writing through to the backing state (or vice-versa) — "
                "update the model in the same handler that flips the label, and bind aria-checked/checked to it.")
    return "Review the control's handler against the expected behavior."


def _record(session, c: Candidate, frame: str | None) -> str:
    f = build_finding(
        session_id=session.record.id, trace_id=session.record.trace_id,
        summary=c.issue, expected=c.expected, actual=c.actual,
        suspected_area=f"region:{c.region_id} oracle:{c.evidence.get('oracle', c.lens)}",
        severity=_SEV.get(c.severity, Severity.MEDIUM),
        screenshot_refs=[frame] if frame else [], bbox=list(c.bbox),
    )
    session.trace.save_finding(f)
    session.record.findings.append(f.id)
    return f.id


def _latest_frame(session) -> str | None:
    n = getattr(session.trace, "_frame_n", 0)
    return f"frame_{n - 1:04d}.png" if n > 0 else None


def run_regions(session, max_regions: int = 8, max_hypotheses: int = 12) -> dict:
    session.observe()
    elements = capture(session)  # interactive + displayed text
    regions = segment(elements)[:max_regions]
    candidates: list[Candidate] = []
    fixes: list[dict] = []
    tested = 0

    for region in regions:
        region_els = [e for e in elements if e.id in region.member_ids]
        for lens in LENSES:
            for hyp in lens.detect(session, region, region_els):
                if tested >= max_hypotheses:
                    break
                tested += 1
                cand = lens.investigate(session, region, hyp)
                if cand is None:
                    continue
                fid = _record(session, cand, _latest_frame(session))
                candidates.append(cand)
                fixes.append({
                    "finding_id": fid,
                    "region": {"region_id": region.region_id, "title": region.title,
                               "role_class": region.role_class, "bbox": [round(v, 4) for v in region.bbox]},
                    "lens": cand.lens, "issue": cand.issue,
                    "evidence": cand.evidence, "expected": cand.expected, "actual": cand.actual,
                    "suggested_fix": _suggested_fix(cand),
                    "severity": cand.severity, "confidence": "high",  # measured, not inferred
                })

    fixes.sort(key=lambda f: -{"critical": 3, "high": 2, "medium": 1, "low": 0}.get(f["severity"], 0))
    return {
        "scope": "full",
        "regions_mapped": len(regions),
        "hypotheses_tested": tested,
        "confirmed": len(candidates),
        "fixes": fixes,
        "regions": [{"region_id": r.region_id, "title": r.title, "role_class": r.role_class,
                     "bbox": [round(v, 4) for v in r.bbox], "members": len(r.member_ids)} for r in regions],
    }
