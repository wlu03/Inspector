"""Typed, evidence-returning assertions for verification (P0.1).

An Assertion is a machine-checkable claim about the current observation: text, role,
value, count, URL, accessibility state, network, or a screenshot region. Each evaluates
to pass / fail / inconclusive **with evidence**. Channels that aren't available on the
surface (or aren't implemented yet, e.g. the screenshot baseline) return `inconclusive`
with a reason rather than silently passing, so a green result always means a real check
ran. That is the whole contract of this module, and it is why "the channel saw nothing"
and "the channel does not exist here" are kept scrupulously apart — the first is a real
observation that can pass or fail an assertion, the second can only ever be inconclusive.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel


class AssertionKind(str, Enum):
    TEXT = "text"          # some text is present/absent on screen
    ROLE = "role"          # an element with this ARIA role exists
    VALUE = "value"        # the element `on` has this value
    COUNT = "count"        # number of elements matching `target`
    URL = "url"            # the current URL contains/equals `target`
    STATE = "state"        # a11y state (`target`, e.g. checked) of element `on`
    NETWORK = "network"    # a request matching `target` returned `expected`
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


_STATUS_CLASS = re.compile(r"([1-5])xx")
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _request_matches(rec: dict, target: str) -> bool:
    """Whether one captured request is the one the assertion is talking about.

    `target` is a substring of the URL, optionally prefixed by a method — enough to say
    the useful things without inventing a matcher language. "/api/items" picks the
    endpoint whatever host it is on, a full URL pins it exactly, "POST /api/items"
    separates the write from the read of the same route, and an empty target means every
    request, so "nothing anywhere 5xx'd" is expressible.
    """
    t = (target or "").strip().lower()
    if not t:
        return True
    method = str(rec.get("method") or "").lower()
    url = str(rec.get("url") or "").lower()
    if t in _HTTP_METHODS:
        return method == t
    verb, _, rest = t.partition(" ")
    if verb in _HTTP_METHODS and rest.strip():
        return method == verb and rest.strip() in url
    return t in url


def _status_token(expected) -> str | None:
    """Normalize `expected` into a status matcher, or None if it isn't one.

    Accepts an exact code (500, "404"), a class ("5xx"), or the two outcomes a caller
    naturally reaches for: "ok" (any 2xx/3xx) and "failed" (the request never completed).
    Anything else is a malformed assertion rather than a false one, and the caller is
    told so — silently failing an unreadable expectation would look exactly like a bug
    in the app.
    """
    want = str(expected).strip().lower()
    if want in ("ok", "success", "failed", "error"):
        return want
    if _STATUS_CLASS.fullmatch(want):
        return want
    if want.isdigit() and 100 <= int(want) <= 599:
        return want
    return None


def _status_matches(rec: dict, want: str) -> bool:
    status = rec.get("status")
    if want in ("failed", "error"):
        return bool(rec.get("failed"))
    if want in ("ok", "success"):
        return isinstance(status, int) and 200 <= status < 400
    if not isinstance(status, int):
        return False  # never completed: it matches no status code, only "failed"
    m = _STATUS_CLASS.fullmatch(want)
    return status // 100 == int(m.group(1)) if m else status == int(want)


def _describe_request(rec: dict) -> str:
    """One request as evidence: `GET /api/items 500`, or the error it died with."""
    if rec.get("failed"):
        outcome = str(rec.get("error") or "failed")[:80]
    elif isinstance(rec.get("status"), int):
        outcome = str(rec["status"])
    else:
        outcome = "pending"
    return f"{rec.get('method') or 'GET'} {str(rec.get('url') or '')[:120]} {outcome}"


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
                       states=None, network=None,
                       screenshot: bool = False) -> AssertionResult:
    """Evaluate one assertion against the channels the caller managed to gather.

    `network` is the list of request records drained for this observation (the shape
    `SurfaceAdapter.network()` returns). Anything that is not a list — None, or the
    historical False — means the surface has no network tap at all, which is the one
    case a NETWORK assertion may answer `inconclusive`. An EMPTY list is the opposite:
    the tap ran and saw no traffic, which is a real finding about the app.
    """
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

    if a.kind == AssertionKind.NETWORK:
        if not isinstance(network, list):
            return _res(a, Status.INCONCLUSIVE,
                        evidence="this surface has no network channel, so nothing was "
                                 "captured to check (web/Electron capture over CDP)")
        matched = [r for r in network if _request_matches(r, a.target)]
        seen = "; ".join(_describe_request(r) for r in matched[:5]) or "none"
        absent = a.op == AssertionOp.ABSENT
        if a.expected is None:
            # No expected status: the claim is only that such a request happened at all.
            ok = (not matched) if absent else bool(matched)
            return _res(a, Status.PASS if ok else Status.FAIL, actual=len(matched),
                        evidence=f"{len(matched)} of {len(network)} captured request(s) "
                                 f"match {a.target!r}: {seen}")
        if a.op in (AssertionOp.GTE, AssertionOp.LTE):
            hits = [r for r in matched
                    if isinstance(r.get("status"), int) and _cmp_num(r["status"], a.expected, a.op)]
        else:
            want = _status_token(a.expected)
            if want is None:
                return _res(a, Status.INCONCLUSIVE,
                            evidence=f"expected {a.expected!r} is not a status: use a code "
                                     f"(500), a class (5xx), 'ok', or 'failed'")
            hits = [r for r in matched if _status_matches(r, want)]
        ok = (not hits) if absent else bool(hits)
        return _res(a, Status.PASS if ok else Status.FAIL, actual=seen,
                    evidence=f"{len(hits)} of {len(matched)} request(s) matching "
                             f"{a.target!r} {a.op.value} {a.expected}: {seen}")

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
