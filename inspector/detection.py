from __future__ import annotations

import re

from .models import Confidence, Finding, Severity

# Deterministic crash/error markers (high confidence). The visual/judgment
# detectors (pixel-diff, layout) are added later — see docs/05 + docs/11 Part M.
_MARKERS = [
    (re.compile(r"\bFATAL\b|AndroidRuntime|\bANR\b"), Severity.CRITICAL),
    (re.compile(r"\b(uncaught|unhandled)\b.*(exception|rejection)", re.I), Severity.HIGH),
    (re.compile(r"\bTypeError\b|\bReferenceError\b|\bSyntaxError\b", re.I), Severity.HIGH),
    (re.compile(r"\berror\b", re.I), Severity.MEDIUM),
]

# A source location: an optional URL origin, then path.ext:line(:col). Matches
# browser stack frames (http://localhost:5173/main.js:8:10), absolute paths, and
# native frames (MainActivity.java:42).
_LOCATION = re.compile(
    r"(?:[a-z][a-z0-9+.\-]*://[^\s()]+/)?"          # optional scheme://host/ prefix
    r"([\w.\-/@]+\.[A-Za-z][\w]*)"                  # path ending in .ext
    r":(\d+)(?::\d+)?"                              # :line(:col)
)

# Lines that are pure stack frames / noise (no value as a standalone finding).
_NOISE = re.compile(r"^\s*at\s", re.I)


def extract_location(text: str) -> str | None:
    """Return the most specific `file:line` from a log/stack line, origin-stripped."""
    match = None
    for match in _LOCATION.finditer(text):
        pass  # keep the last (innermost / most specific) frame
    if match is None:
        return None
    return f"{match.group(1)}:{match.group(2)}"


def finding_signature(finding: Finding) -> str:
    """A stable key for de-duplicating findings across observe/act calls."""
    summary = re.sub(r"\d+", "#", finding.summary)  # collapse volatile numbers
    return f"{finding.severity.value}|{finding.suspected_area}|{summary[:120]}"


def scan_logs(lines: list[str], session_id: str = "", trace_id: str = "") -> list[Finding]:
    """Turn raw log lines into enriched, deterministic Findings.

    Enrichment: pull `file:line` from the matching line or the nearby stack frames,
    and skip pure stack-frame lines (so the finding is the error, not each frame).
    """
    findings: list[Finding] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or _NOISE.match(line):
            continue
        for pattern, severity in _MARKERS:
            if pattern.search(line):
                location = extract_location(line)
                if not location:  # look ahead a few stack frames for the source
                    for nxt in lines[i + 1 : i + 6]:
                        location = extract_location(nxt)
                        if location:
                            break
                findings.append(
                    Finding(
                        session_id=session_id,
                        trace_id=trace_id,
                        summary=line[:200],
                        severity=severity,
                        confidence=Confidence.HIGH,
                        actual=line,
                        logs=[line],
                        suspected_area=location or "(from log tap)",
                    )
                )
                break
    return findings
