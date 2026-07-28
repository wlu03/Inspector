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


def build_repro_spec(session, oracle=None):
    """A durable, replayable spec for a finding: surface, route, preconditions, semantic
    steps (by element label, not raw coordinates), and an explicit oracle. Lets
    re-verification replay the exact scenario and check a real condition.

    `oracle` is a list of Assertions describing the CORRECT behavior — what PASSES once
    the bug is fixed, never a description of the bug itself. When the caller has none,
    the spec inherits the last assertion set evaluated on this session
    (`session.last_assertions`, recorded by the `check_assertions` tool): a log-tap or
    DOM-audit finding filed right after a failing `check_assertions` is almost always
    about that same expectation, so it should re-verify against that real check instead
    of falling back to digit-normalized summary matching.
    """
    import re

    from .models import ReproSpec, ReproStep

    steps: list[ReproStep] = []
    for entry in getattr(session, "action_log", None) or []:
        m = re.match(r"type '(.*)'$", entry)
        if m:
            steps.append(ReproStep(action="type", text=m.group(1)))
            continue
        m = re.match(r"press '(.*)'$", entry)
        if m:
            steps.append(ReproStep(action="key", key=m.group(1)))
            continue
        m = re.match(r"([\w ]+?) element #\d+(?: \((.*)\))?$", entry)
        if m:
            steps.append(ReproStep(action=m.group(1).strip().replace(" ", "_"),
                                   locator=(m.group(2) or "")))
            continue
        steps.append(ReproStep(action=entry.strip()))

    rec = getattr(session, "record", None)
    surface = getattr(getattr(rec, "surface", None), "value", "") or ""
    route = ""
    cdp = getattr(getattr(session, "adapter", None), "cdp", None)
    if cdp is not None:
        try:
            v = cdp.evaluate("window.location.href")
            route = v.strip('"') if isinstance(v, str) else (v or "")
        except Exception:
            route = ""
    pre = [f"surface={surface}"] + ([f"route={route}"] if route else [])
    oracle = oracle or getattr(session, "last_assertions", None) or []
    return ReproSpec(surface=surface, route=route, preconditions=pre,
                     steps=steps, oracle=list(oracle))
