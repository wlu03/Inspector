from __future__ import annotations

from .models import Confidence, Finding, Severity


def build_finding(
    *,
    session_id: str,
    trace_id: str,
    summary: str,
    expected: str = "",
    actual: str = "",
    repro: list[str] | None = None,
    logs: list[str] | None = None,
    suspected_area: str = "",
    severity: Severity = Severity.MEDIUM,
    confidence: Confidence = Confidence.MEDIUM,
    screenshot_refs: list[str] | None = None,
    bbox: list[float] | None = None,
) -> Finding:
    """Helper to synthesize a structured Finding the host agent can act on."""
    return Finding(
        session_id=session_id,
        trace_id=trace_id,
        summary=summary,
        expected=expected,
        actual=actual,
        repro=repro or [],
        logs=logs or [],
        suspected_area=suspected_area,
        severity=severity,
        confidence=confidence,
        screenshot_refs=screenshot_refs or [],
        bbox=bbox or [],
    )
