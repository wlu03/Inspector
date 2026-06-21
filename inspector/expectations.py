from __future__ import annotations

import re
from dataclasses import dataclass

from .findings import build_finding
from .models import Confidence, Finding, Severity

_SEVERITY = {s.value: s for s in Severity}


@dataclass(frozen=True)
class ExpectedElement:
    """An interactive element the SOURCE CODE says should exist.

    Surface-agnostic: produced by per-framework scanners (JSX/HTML, Compose/XML,
    SwiftUI/UIKit) and diffed against what actually rendered (`adapter.rendered_elements`).
    """

    label: str
    kind: str          # button | link | input | element
    source_ref: str    # "relpath:line" — so a finding can cite where it's declared


def _norm(s: str) -> str:
    """Compact, comparable form: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def diff_expected_vs_actual(
    expected: list[ExpectedElement], actual: list[str]
) -> list[ExpectedElement]:
    """Expected elements with no match among the actually-rendered labels. Pure.

    Matching is fuzzy-but-cheap: normalized equality OR containment either way
    (so "Save" matches a rendered "Save settings"). Candidates are de-duped by
    normalized label, keeping the first source_ref.
    """
    actual_norm = [_norm(a) for a in actual if _norm(a)]
    out: list[ExpectedElement] = []
    seen: set[str] = set()
    for e in expected:
        ne = _norm(e.label)
        if not ne or ne in seen:
            continue
        # Match on equality, or substring ONLY for labels long enough that containment
        # is meaningful (>=4 chars) — so "ok"/"x" don't spuriously match "Bookmarks".
        # The reverse (rendered-in-expected) direction is dropped: a tiny rendered
        # label shouldn't satisfy a long expected one.
        present = any(ne == na or (len(ne) >= 4 and ne in na) for na in actual_norm)
        if not present:
            seen.add(ne)
            out.append(e)
    return out


def check_expectations(session, expected: list[ExpectedElement], judge_fn) -> list[Finding]:
    """The code-aware "missing element" oracle, run once against the current screen.

    1. ask the adapter what ACTUALLY rendered (per-surface hook),
    2. diff against what the code declared,
    3. let `judge_fn` (the brain) decide which absences are real bugs vs. legitimately
       off-screen (conditional/route rendering),
    4. record each confirmed miss as a Finding citing the source location.

    `judge_fn(candidate, rendered, screenshot) -> {is_bug, severity?, reason?}`.
    Returns [] (oracle no-ops) on surfaces that can't enumerate yet.
    """
    try:
        actual = session.adapter.rendered_elements()
    except NotImplementedError:
        return []  # surface's enumeration not wired yet → skip silently
    except Exception:
        actual = []

    candidates = diff_expected_vs_actual(expected, actual)
    if not candidates:
        return []

    # Sanity guard against blank / mid-navigation frames: the oracle is only credible
    # when the screen actually rendered. If we captured no labels, or MOST of what the
    # code declares looks "missing", that's a bad frame (or a CDP hiccup) — not N real
    # defects. A genuine miss is a few absences among many present elements, so require
    # a solid baseline of present elements before trusting any absence.
    present = len(expected) - len(candidates)
    if not actual or present < max(2, len(expected) * 0.4):
        return []

    try:
        screenshot = session.adapter.screenshot()
    except Exception:
        screenshot = b""

    findings: list[Finding] = []
    for c in candidates:
        try:
            verdict = judge_fn(c, actual, screenshot) or {}
        except Exception:
            continue  # a judgment hiccup shouldn't drop the whole check
        if not verdict.get("is_bug"):
            continue
        severity = _SEVERITY.get(str(verdict.get("severity", "")).lower(), Severity.MEDIUM)
        finding = build_finding(
            session_id=session.record.id,
            trace_id=session.record.trace_id,
            summary=f"Expected UI element not rendered: {c.label!r} ({c.kind})",
            expected=f"{c.kind} {c.label!r} declared at {c.source_ref} should be visible",
            actual=str(verdict.get("reason") or "not present in the rendered UI"),
            suspected_area=c.source_ref,
            severity=severity,
            confidence=Confidence.MEDIUM,  # source vs runtime is inferential, not a crash
        )
        session.trace.save_finding(finding)
        session.record.findings.append(finding.id)
        findings.append(finding)
    return findings
