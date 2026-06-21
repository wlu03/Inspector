"""Deterministic lens oracles (Phase 0): LOGIC_ARITHMETIC + STATE_SYNC.

Each lens: detect() proposes falsifiable hypotheses bound to a control in a region;
investigate() runs a CAPTURE -> TRIGGER (one primitive action) -> MEASURE protocol
and asserts an equality on the app's OWN observable state. No payloads are typed and
no judgement is made on injected input, so these lenses cannot raise self-inflicted
false positives (docs/15 §4 Tier A, §5).
"""

from __future__ import annotations

import re

from ..models import ActionType, Element
from .capture import capture
from .models import Candidate, Hypothesis, norm

_INT_RE = re.compile(r"-?\d+")
_INCREMENT = {"+", "plus", "add", "increment", "up", "▲", "△", "+1"}
_RESET = {"reset", "clear", "clear all", "reset all"}


def _parse_int(label: str | None) -> int | None:
    m = _INT_RE.search(label or "")
    return int(m.group()) if m else None


def _center(b: list[float]) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _in_region(el: Element, region) -> bool:
    if el.id in region.member_ids:
        return True
    cx, cy = _center(el.bbox)
    x1, y1, x2, y2 = region.bbox
    m = 0.02
    return x1 - m <= cx <= x2 + m and y1 - m <= cy <= y2 + m


def _find_number(els: list[Element], region) -> Element | None:
    cands = [e for e in els if not e.interactivity and _parse_int(e.label) is not None and _in_region(e, region)]
    return min(cands, key=lambda e: e.bbox[1]) if cands else None  # top-most number


def _find_button(els: list[Element], region, label_norm: str) -> Element | None:
    return next((e for e in els if e.interactivity and norm(e.label) == label_norm and _in_region(e, region)), None)


def _expected_delta(btn_label: str) -> int:
    # "+5" / "Add 5" -> 5 ; bare + / Plus / Increment -> 1
    n = _parse_int(btn_label)
    return n if n not in (None, 0) else 1


def _log_candidate(lens: str, region, control_label: str, logs: list[str]) -> Candidate | None:
    """Log tier: a real error/crash logged by the control's handler during the trigger,
    even when the UI/a11y state shows no symptom (docs/15 §4 — oracle OR scan_logs)."""
    from ..detection import scan_logs
    hits = scan_logs(list(logs or []))
    if not hits:
        return None
    msg = (hits[0].summary or hits[0].logs[0] if hits[0].logs else "")[:120]
    return Candidate(lens, region.region_id,
                     f"{control_label!r} logged an error on interaction: {msg[:70]}",
                     "no error logged on interaction", msg, str(hits[0].severity.value), region.bbox,
                     {"oracle": "LOG_SIGNAL", "logs": list(logs or [])[:3]})


class LogicArithmeticLens:
    name = "logic_arithmetic"

    def detect(self, session, region, els: list[Element]) -> list[Hypothesis]:
        num = _find_number(els, region)
        if num is None:
            return []
        hyps: list[Hypothesis] = []
        for e in els:
            if not e.interactivity or not _in_region(e, region):
                continue
            nl = norm(e.label)
            if nl in _INCREMENT or (nl.startswith("+") and _parse_int(nl) is not None):
                d = _expected_delta(e.label)
                hyps.append(Hypothesis(self.name, region.region_id, e.label,
                                       f"tapping {e.label!r} raises the number by exactly {d}",
                                       {"kind": "increment", "btn": e.label, "delta": d}))
            elif nl in _RESET:
                hyps.append(Hypothesis(self.name, region.region_id, e.label,
                                       f"tapping {e.label!r} returns the number to 0",
                                       {"kind": "reset", "btn": e.label}))
        return hyps

    def investigate(self, session, region, hyp: Hypothesis) -> Candidate | None:
        els = capture(session)
        num = _find_number(els, region)
        btn = _find_button(els, region, norm(hyp.meta["btn"]))
        if num is None or btn is None:
            return None
        before = _parse_int(num.label)
        try:
            _s, _c, logs = session.act(ActionType.CLICK, btn.id, None, None)
        except Exception:
            return None
        cand = None
        num2 = _find_number(capture(session), region)
        after = _parse_int(num2.label) if num2 else None
        if after is not None and before is not None:
            if hyp.meta["kind"] == "increment":
                d, obs = hyp.meta["delta"], after - before
                if obs != d:
                    cand = Candidate(self.name, region.region_id,
                                     f"{hyp.meta['btn']!r} changes the value by {obs} instead of {d}",
                                     f"delta == {d}", f"delta == {obs}", "high", region.bbox,
                                     {"before": before, "after": after, "oracle": f"COUNTER_DELTA observed={obs} expected={d}"})
            elif after != 0:
                cand = Candidate(self.name, region.region_id,
                                 f"{hyp.meta['btn']!r} sets the value to {after} instead of 0",
                                 "value == 0 after reset", f"value == {after}", "medium", region.bbox,
                                 {"before": before, "after": after, "oracle": f"RESET_TO observed={after} expected=0"})
        return cand or _log_candidate(self.name, region, hyp.meta["btn"], logs)


def _toggle_state(cs: dict) -> tuple | None:
    """A signature of a control's togglable state, or None if it isn't a toggle."""
    keys = [cs.get("checked"), cs.get("pressed"), cs.get("ariaChecked"), cs.get("selected")]
    present = [k for k in keys if k not in (None, "", "undefined")]
    if present:
        return tuple(str(k).lower() for k in present)
    # native a11y (iOS/macOS): a switch/checkbox exposes its on/off in "value".
    role = (cs.get("role") or "").lower()
    val = cs.get("value")
    if val not in (None, "", "undefined") and any(t in role for t in ("switch", "checkbox", "toggle", "radio")):
        return (str(val).lower(),)
    return None


class StateSyncLens:
    name = "state_sync"

    def detect(self, session, region, els: list[Element]) -> list[Hypothesis]:
        hyps: list[Hypothesis] = []
        cs_fn = getattr(session.adapter, "control_state", None)
        if cs_fn is None:
            return hyps
        for e in els:
            if not e.interactivity or not _in_region(e, region):
                continue
            cs = cs_fn(e.id) or {}
            if _toggle_state(cs) is not None:
                hyps.append(Hypothesis(self.name, region.region_id, e.label,
                                       "toggling the control flips its label AND its underlying state together",
                                       {"label": e.label, "elem_id": e.id}))
        return hyps

    def investigate(self, session, region, hyp: Hypothesis) -> Candidate | None:
        cs_fn = session.adapter.control_state
        els = capture(session)
        tog = _find_button(els, region, norm(hyp.meta["label"]))
        if tog is None:
            # label may already have flipped (On/Off); fall back to the recorded id
            tog = next((e for e in els if e.id == hyp.meta.get("elem_id")), None)
        if tog is None:
            return None
        before_label = tog.label
        before_state = _toggle_state(cs_fn(tog.id) or {})
        try:
            _s, _c, logs = session.act(ActionType.CLICK, tog.id, None, None)
        except Exception:
            return None
        els2 = capture(session)
        # re-find the same control near the same spot
        tog2 = next((e for e in els2 if e.interactivity and _in_region(e, region)
                     and abs(_center(e.bbox)[1] - _center(tog.bbox)[1]) < 0.04), tog)
        after_label = tog2.label
        after_state = _toggle_state(cs_fn(tog2.id) or {})
        label_changed = norm(before_label) != norm(after_label)
        state_changed = before_state != after_state
        cand = None
        if label_changed != state_changed:  # XOR — visible label and backing state disagree
            cand = Candidate(self.name, region.region_id,
                             f"toggle {hyp.meta['label']!r}: the visible label and its state disagree after a tap",
                             "label and aria/checked state change together",
                             f"label {before_label!r}->{after_label!r} (changed={label_changed}) but state {before_state}->{after_state} (changed={state_changed})",
                             "medium", region.bbox,
                             {"before": {"label": before_label, "state": before_state},
                              "after": {"label": after_label, "state": after_state},
                              "oracle": f"CONTROL_STATE_MATCHES_LABEL label_changed={label_changed} state_changed={state_changed}"})
        elif not label_changed and not state_changed:  # INERT — a toggle that moves nothing
            cand = Candidate(self.name, region.region_id,
                             f"toggle {hyp.meta['label']!r} is inert — tapping it changes neither its label nor its state",
                             "tapping a toggle flips its state",
                             f"label {before_label!r} and state {before_state} both unchanged after a tap",
                             "medium", region.bbox,
                             {"before": {"label": before_label, "state": before_state},
                              "after": {"label": after_label, "state": after_state},
                              "oracle": "TOGGLE_INERT: no change on tap"})
        return cand or _log_candidate(self.name, region, hyp.meta["label"], logs)


_SAVE = {"save", "submit", "continue", "apply", "done", "update", "confirm", "ok"}
_FIELD_ROLES = {"textfield", "textarea", "input", "searchfield", "combobox"}


class PersistenceLens:
    """A value typed into a field must survive a Save/Submit (catches macOS 'Save
    clears the name'). Uses a benign realistic sentinel — NEVER a payload — so a
    lost/blank read is unambiguously the app's fault, not self-injection (docs/15 §4)."""

    name = "persistence"
    SENTINEL = "Insp3ctorName"

    @staticmethod
    def _field(els, region) -> Element | None:
        return next((e for e in els if e.interactivity and e.role in _FIELD_ROLES and _in_region(e, region)), None)

    def detect(self, session, region, els: list[Element]) -> list[Hypothesis]:
        field = self._field(els, region)
        save = next((e for e in els if e.interactivity and norm(e.label) in _SAVE and _in_region(e, region)), None)
        if field is None or save is None:
            return []
        return [Hypothesis(self.name, region.region_id, save.label,
                           f"a value typed into the field persists after tapping {save.label!r}",
                           {"save": save.label})]

    def investigate(self, session, region, hyp: Hypothesis) -> Candidate | None:
        field = self._field(capture(session), region)
        if field is None:
            return None
        try:
            session.act(ActionType.TYPE, field.id, self.SENTINEL, None)
        except Exception:
            return None
        save = _find_button(capture(session), region, norm(hyp.meta["save"]))
        if save is None:
            return None
        try:
            session.act(ActionType.CLICK, save.id, None, None)
        except Exception:
            return None
        field2 = self._field(capture(session), region)
        val = field2.label if field2 else ""
        if self.SENTINEL.lower() not in norm(val):
            return Candidate(self.name, region.region_id,
                             f"the typed value was lost after tapping {hyp.meta['save']!r}",
                             f"the field still shows {self.SENTINEL!r}", f"the field shows {val!r}",
                             "high", region.bbox,
                             {"sentinel": self.SENTINEL, "after": val,
                              "oracle": "FIELD_PERSISTS: sentinel not present after save"})
        return None


LENSES = [LogicArithmeticLens(), StateSyncLens(), PersistenceLens()]
