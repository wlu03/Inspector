"""Typed, evidence-returning assertions for verification (P0.1).

An Assertion is a machine-checkable claim about the current observation: text, role,
value, count, URL, accessibility state, network, or a screenshot region. Each evaluates
to pass / fail / inconclusive **with evidence**. Channels that aren't available on the
surface (or aren't implemented yet, e.g. network/screenshot) return `inconclusive` with
a reason rather than silently passing, so a green result always means a real check ran.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class AssertionKind(str, Enum):
    TEXT = "text"          # some text is present/absent on screen
    ROLE = "role"          # an element with this ARIA role exists
    VALUE = "value"        # the element `on` has this value
    COUNT = "count"        # number of elements matching `target`
    URL = "url"            # the current URL contains/equals `target`
    STATE = "state"        # a11y state (`target`, e.g. checked) of element `on`
    NETWORK = "network"    # a request matching `target` returned `expected` (needs capture)
    SCREENSHOT = "screenshot"  # a screenshot region matches a baseline (needs baseline)


class AssertionOp(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    EQUALS = "equals"
    CONTAINS = "contains"
    GTE = "gte"
    LTE = "lte"


class Assertion(BaseModel):
    kind: AssertionKind
    target: str = ""                  # text / role / url substring / state name / matcher
    op: AssertionOp = AssertionOp.PRESENT
    expected: str | int | None = None
    on: str = ""                      # element label to locate (value/state assertions)


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class AssertionResult(BaseModel):
    kind: AssertionKind
    target: str = ""
    op: AssertionOp = AssertionOp.PRESENT
    status: Status
    expected: str | int | None = None
    actual: str | int | None = None
    evidence: str = ""


def _res(a: Assertion, status: Status, actual=None, evidence: str = "") -> AssertionResult:
    return AssertionResult(kind=a.kind, target=a.target, op=a.op, status=status,
                           expected=a.expected, actual=actual, evidence=evidence)


def _matches(el: dict, target: str) -> bool:
    t = target.lower()
    return t in el.get("label", "").lower() or el.get("role", "").lower() == t


def _cmp_num(actual: int, expected, op: AssertionOp) -> bool:
    try:
        e = int(expected)
    except (TypeError, ValueError):
        return False
    if op == AssertionOp.GTE:
        return actual >= e
    if op == AssertionOp.LTE:
        return actual <= e
    return actual == e


def evaluate_assertion(a: Assertion, *, texts=None, elements=None, url=None,
                       states=None, network: bool = False,
                       screenshot: bool = False) -> AssertionResult:
    texts = texts or []
    elements = elements or []
    states = states or {}

    if a.kind == AssertionKind.TEXT:
        present = bool(a.target) and a.target.lower() in "\n".join(texts).lower()
        want = a.op != AssertionOp.ABSENT
        return _res(a, Status.PASS if present == want else Status.FAIL,
                    actual="present" if present else "absent",
                    evidence=f"text {a.target!r} {'found' if present else 'not found'} "
                             f"in {len(texts)} text nodes")

    if a.kind == AssertionKind.ROLE:
        found = any(e.get("role", "").lower() == a.target.lower() for e in elements)
        want = a.op != AssertionOp.ABSENT
        return _res(a, Status.PASS if found == want else Status.FAIL,
                    actual="present" if found else "absent",
                    evidence=f"role {a.target!r} {'present' if found else 'absent'} "
                             f"among {len(elements)} elements")

    if a.kind == AssertionKind.COUNT:
        n = sum(1 for e in elements if _matches(e, a.target))
        ok = _cmp_num(n, a.expected, a.op)
        return _res(a, Status.PASS if ok else Status.FAIL, actual=n,
                    evidence=f"{n} element(s) match {a.target!r} "
                             f"(op {a.op.value} {a.expected})")

    if a.kind == AssertionKind.URL:
        if url is None:
            return _res(a, Status.INCONCLUSIVE, evidence="URL not available on this surface")
        ok = (url.lower() == a.target.lower()) if a.op == AssertionOp.EQUALS \
            else (a.target.lower() in url.lower())
        return _res(a, Status.PASS if ok else Status.FAIL, actual=url,
                    evidence=f"current URL {url!r}")

    if a.kind in (AssertionKind.VALUE, AssertionKind.STATE):
        st = states.get(a.on.lower())
        if st is None:
            return _res(a, Status.INCONCLUSIVE,
                        evidence=f"element {a.on!r} not found or its state is unavailable")
        key = "value" if a.kind == AssertionKind.VALUE else (a.target or "checked")
        actual = st.get(key)
        ok = str(actual).lower() == str(a.expected).lower()
        return _res(a, Status.PASS if ok else Status.FAIL, actual=actual,
                    evidence=f"{a.on!r} {key}={actual!r}")

    if a.kind == AssertionKind.NETWORK and not network:
        return _res(a, Status.INCONCLUSIVE,
                    evidence="network capture not available yet (network tools are a separate P0 item)")
    if a.kind == AssertionKind.SCREENSHOT and not screenshot:
        return _res(a, Status.INCONCLUSIVE,
                    evidence="screenshot-region baseline not available")
    return _res(a, Status.INCONCLUSIVE, evidence=f"assertion kind {a.kind.value} not implemented")


def evaluate_assertions(assertions, **ctx) -> list[AssertionResult]:
    return [evaluate_assertion(a, **ctx) for a in assertions]


def summarize(results) -> dict:
    counts = {"pass": 0, "fail": 0, "inconclusive": 0}
    for r in results:
        counts[r.status.value] += 1
    overall = "fail" if counts["fail"] else ("inconclusive" if counts["inconclusive"] else "pass")
    return {"overall": overall, "counts": counts}
