from __future__ import annotations

from .findings import build_finding
from .models import Confidence, Finding, Severity

# axe-core impact → our severity. axe's own taxonomy, mapped 1:1.
_AXE_IMPACT_SEVERITY = {
    "critical": Severity.CRITICAL,
    "serious": Severity.HIGH,
    "moderate": Severity.MEDIUM,
    "minor": Severity.LOW,
}


def audit_to_findings(
    audit: dict, *, session_id: str = "", trace_id: str = ""
) -> list[Finding]:
    """Turn a deterministic DOM audit into structured Findings. Pure.

    This is the strongest evidence tier: every finding is a structured FACT read
    from the live DOM (an axe rule id + node count, a zero naturalWidth, a missing
    label) rather than a vision judgment — the same rigor ui-test gets from
    `browse eval`. Degrades to [] on an empty/failed audit.
    """
    findings: list[Finding] = []

    for v in audit.get("axe_violations") or []:
        if not isinstance(v, dict):
            continue
        impact = str(v.get("impact") or "moderate").lower()
        sev = _AXE_IMPACT_SEVERITY.get(impact, Severity.MEDIUM)
        rule = str(v.get("id") or "?")
        nodes = v.get("nodes", 0)
        findings.append(build_finding(
            session_id=session_id, trace_id=trace_id,
            summary=f"a11y: {v.get('help') or rule} ({rule})"[:200],
            expected="no serious/critical axe-core (WCAG) violations",
            actual=f"axe rule {rule!r} ({impact}) failed on {nodes} node(s)",
            suspected_area=f"axe:{rule}",
            severity=sev, confidence=Confidence.HIGH,
            repro=["deterministic DOM audit (axe-core)"],
        ))

    broken = [b for b in (audit.get("broken_images") or []) if b]
    if broken:
        findings.append(build_finding(
            session_id=session_id, trace_id=trace_id,
            summary=f"{len(broken)} broken image(s) (naturalWidth=0)",
            expected="every <img> loads (naturalWidth > 0)",
            actual="failed to load: " + ", ".join(str(b) for b in broken[:8]),
            suspected_area="broken-images",
            severity=Severity.MEDIUM, confidence=Confidence.HIGH,
            repro=["deterministic DOM audit (images)"],
        ))

    unlabeled = [u for u in (audit.get("unlabeled_inputs") or []) if u]
    if unlabeled:
        findings.append(build_finding(
            session_id=session_id, trace_id=trace_id,
            summary=f"{len(unlabeled)} form input(s) with no accessible label",
            expected="every input has a label / aria-label / placeholder",
            actual="unlabeled: " + ", ".join(str(u) for u in unlabeled[:8]),
            suspected_area="form-labels",
            severity=Severity.MEDIUM, confidence=Confidence.HIGH,
            repro=["deterministic DOM audit (labels)"],
        ))

    return findings
