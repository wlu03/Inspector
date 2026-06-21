from __future__ import annotations

import json
import os

from .driver import Decision
from .findings import build_finding
from .models import Severity

_SEVERITY = {s.value: s for s in Severity}

# Labels that mark OS desktop / browser chrome — never part of the app under test.
# Defense-in-depth: the panel is killed at launch, but if any OS chrome sneaks into
# the frame, the explorer must not click it and wander off the app.
_CHROME_TERMS = (
    "firefox", "mozilla", "add-on", "internet browser", "file system",
    "file manager", "terminal", "trash", "applications", "workspace",
    "whisker", "xfce", "taskbar", "wastebasket", "home folder",
)


# Soft-keyboard keys (iOS/Android) flood the a11y tree after a TYPE action — the
# loop must not target them or it wanders off typing 'Q' instead of testing the app.
_KEYBOARD_LABELS = {
    "space", "return", "delete", "shift", "more", "emoji", "dictate", "done",
    "go", "search", "next", "globe", "backspace", "caps lock", "tab",
}


def _is_keyboard_key(e) -> bool:
    label = (e.label or "").strip()
    role = (e.role or "").lower()
    if "keyboard" in role or role == "key":
        return True
    if label.lower() in _KEYBOARD_LABELS:
        return True
    # a single visible character is almost always a soft-keyboard key
    return len(label) == 1 and not label.isspace()


def _confine(elements: list) -> list:
    """Drop OS/browser chrome and soft-keyboard keys, keeping the explorer in-app."""
    out = []
    for e in elements:
        label = (e.label or "").lower()
        if any(term in label for term in _CHROME_TERMS):
            continue
        if _is_keyboard_key(e):
            continue
        out.append(e)
    return out


def run_autopilot(session, driver, goal: str, max_steps: int | None = None) -> dict:
    """Drive one app end-to-end: observe → decide → act, until the driver says
    `done` or a LoopGuard tripwire fires. Returns a structured report.

    `session` is a live Session; `driver` is anything with
    `decide(som, elements, goal, history, logs) -> Decision`. Both are injected so
    this loop is unit-testable with fakes (no sandbox, no Replicate).
    """
    som, elements, logs = session.observe()
    # code-aware oracle: surface elements the source declares but that didn't render.
    missing = _check_expected_elements(session, driver)
    history: list[dict] = []
    tried_noop: set[tuple] = set()   # (action, target, text) that already did nothing
    acted: set[int] = set()          # element ids already acted on
    steps = 0
    stop_reason = "model_done"

    while True:
        tripped = session.guard.exhausted()
        if tripped:
            stop_reason = tripped
            break
        if max_steps is not None and steps >= max_steps:
            stop_reason = "max_steps"
            break

        decision = _safe_decide(driver, som, _confine(elements), goal, history, logs)

        if decision.bug:
            # locate the bug on-screen via the element the driver was acting on, so
            # the replay can drop a clickable marker there.
            bbox = _bbox_for(elements, decision.target_id)
            _record_bug(session, decision, history, frame_ref=_latest_frame(session), bbox=bbox)

        if decision.is_done:
            stop_reason = "model_done"
            break

        # de-repetition: if the brain retries an action that already did nothing, force
        # a fresh un-acted interactive element so the run explores instead of fixating.
        sig = (decision.action, decision.target_id, decision.text)
        if sig in tried_noop:
            alt = _next_unvisited(_confine(elements), acted)
            if alt is None:
                stop_reason = "explored"
                break
            decision = Decision(action="click", target_id=alt,
                                reason="de-rep: prior action was a no-op; exploring a new element")
            sig = (decision.action, decision.target_id, decision.text)

        label = _label_for(elements, decision.target_id)
        try:
            som, changed, logs = session.act(
                decision.action_type(), decision.target_id, decision.text, decision.key
            )
            elements = session.last_elements
        except Exception as exc:  # a bad action shouldn't kill the whole run
            history.append(_step(steps, decision, label, changed=False, error=str(exc)))
            som, elements, logs = session.observe()  # re-sync after the failed step
            steps += 1
            continue

        if decision.target_id is not None:
            acted.add(decision.target_id)
        if not changed:
            tried_noop.add(sig)
        history.append(_step(steps, decision, label, changed=changed))
        steps += 1

    _run_dom_audit(session)  # deterministic evidence tier (web/electron; no-ops elsewhere)

    # adversarially verify judgment findings: refute speculative ones before reporting.
    from .verify import confirmed_findings, verify_findings
    verdicts = verify_findings(session, driver)
    findings = confirmed_findings(session)
    return {
        "goal": goal,
        "steps": steps,
        "stop_reason": stop_reason,
        "iterations": session.guard.iterations,
        "findings": findings,             # confirmed only (dismissed kept in the trace)
        "findings_total": len(findings),
        "verification": verdicts,         # {verified, dismissed, trusted}
        "missing_elements": len(missing),
        "history": history,
    }


def _run_dom_audit(session) -> None:
    """Run the deterministic DOM audit once at the end of an autonomous run.

    Fully guarded — any failure (no DOM surface, CDP down, axe unavailable) just
    yields no findings, mirroring the missing-element oracle.
    """
    try:
        session.audit()
    except Exception:
        pass


def _check_expected_elements(session, driver) -> list:
    """Run the code-aware missing-element oracle once for the current screen.

    Surface-agnostic: source_scan provides per-framework expectations, the adapter
    provides what actually rendered, the driver's brain judges each absence. Fully
    guarded — any failure (no scanner, no DOM, no brain) just yields no findings.
    """
    judge = getattr(driver, "judge_missing_element", None)
    if judge is None:
        return []
    try:
        from .expectations import check_expectations
        from .source_scan import extract_expected

        expected = extract_expected(session.record.repo_path, session.record.surface)
        if not expected:
            return []
        return check_expectations(session, expected, judge)
    except Exception:
        return []


def _safe_decide(driver, som, elements, goal, history, logs) -> Decision:
    try:
        return driver.decide(som, elements, goal, history, logs)
    except Exception as exc:
        # a driver/model hiccup becomes a no-op so the loop can keep going and
        # the LoopGuard's no-progress tripwire eventually ends it.
        return Decision(action="wait", reason=f"driver error: {exc}")


def _record_bug(
    session, decision: Decision, history: list[dict], frame_ref: str | None,
    bbox: list[float] | None = None,
) -> None:
    bug = decision.bug or {}
    severity = _SEVERITY.get(str(bug.get("severity", "")).lower(), Severity.MEDIUM)
    # repro = the trail of actions that led here (last few steps), human-readable.
    repro = [
        f"{h['action']} {h.get('target_label', '')}".strip() for h in history[-6:]
    ]
    finding = build_finding(
        session_id=session.record.id,
        trace_id=session.record.trace_id,
        summary=str(bug.get("summary", ""))[:200],
        expected=str(bug.get("expected", "")),
        actual=str(bug.get("actual", "")),
        repro=repro,
        suspected_area=decision.expectation or "(autopilot judgment)",
        severity=severity,
        screenshot_refs=[frame_ref] if frame_ref else [],
        bbox=bbox or [],
    )
    session.trace.save_finding(finding)
    session.record.findings.append(finding.id)


def collect_findings(session) -> list[dict]:
    """Read every finding written this session (log-tap + autopilot judgment)."""
    out: list[dict] = []
    fdir = session.trace.findings_dir
    if os.path.isdir(fdir):
        for name in sorted(os.listdir(fdir)):
            try:
                with open(os.path.join(fdir, name)) as f:
                    out.append(json.load(f))
            except Exception:
                continue
    return out


def _next_unvisited(elements, acted: set[int]) -> int | None:
    """First interactive element id not yet acted on — the de-rep escape hatch."""
    for e in elements:
        if getattr(e, "interactivity", False) and e.id not in acted:
            return e.id
    return None


def _label_for(elements, target_id) -> str:
    if target_id is None:
        return ""
    el = next((e for e in elements if e.id == target_id), None)
    return (el.label if el else "") or ""


def _bbox_for(elements, target_id) -> list[float]:
    """The acted element's bbox (ratios) — the bug's on-screen location for the marker."""
    if target_id is None:
        return []
    el = next((e for e in elements if e.id == target_id), None)
    return list(el.bbox) if el and el.bbox else []


def _latest_frame(session) -> str | None:
    n = getattr(session.trace, "_frame_n", 0)
    return f"frame_{n - 1:04d}.png" if n > 0 else None


def _step(step, decision: Decision, label, changed: bool, error: str | None = None) -> dict:
    return {
        "step": step,
        "action": decision.action,
        "target_id": decision.target_id,
        "target_label": label,
        "text": decision.text,
        "changed": changed,
        "reason": decision.reason,
        "error": error,
    }
