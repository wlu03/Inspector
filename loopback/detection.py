from __future__ import annotations

import re

from .models import Confidence, Finding, Severity

# Deterministic crash/error markers (high confidence). The visual/judgment
# detectors (pixel-diff, layout) are added later — see docs/05 + docs/11 Part M.
_MARKERS = [
    (re.compile(r"\bFATAL\b|AndroidRuntime|\bANR\b"), Severity.CRITICAL),
    (re.compile(r"\b(uncaught|unhandled)\b.*(exception|rejection)", re.I), Severity.HIGH),
    (re.compile(r"\bTypeError\b|\bReferenceError\b|\bSyntaxError\b"), Severity.HIGH),
    (re.compile(r"\berror\b", re.I), Severity.MEDIUM),
]


def scan_logs(lines: list[str], session_id: str = "", trace_id: str = "") -> list[Finding]:
    """Turn raw log lines into deterministic Findings (the most reliable signal)."""
    findings: list[Finding] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        for pattern, severity in _MARKERS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        session_id=session_id,
                        trace_id=trace_id,
                        summary=line[:200],
                        severity=severity,
                        confidence=Confidence.HIGH,
                        actual=line,
                        logs=[line],
                        suspected_area="(from log tap)",
                    )
                )
                break
    return findings
