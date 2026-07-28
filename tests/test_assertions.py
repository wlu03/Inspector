"""Typed assertion evaluation (P0.1): pass / fail / inconclusive with evidence."""

from inspector.assertions import (
    Assertion,
    AssertionKind as K,
    AssertionOp as Op,
    Status,
    evaluate_assertion,
    evaluate_assertions,
    summarize,
)


def test_text_present_and_absent():
    present = Assertion(kind=K.TEXT, target="Saved", op=Op.PRESENT)
    assert evaluate_assertion(present, texts=["Saved", "Home"]).status == Status.PASS
    assert evaluate_assertion(present, texts=["Home"]).status == Status.FAIL
    absent = Assertion(kind=K.TEXT, target="Error", op=Op.ABSENT)
    assert evaluate_assertion(absent, texts=["Home"]).status == Status.PASS
    assert evaluate_assertion(absent, texts=["Error: boom"]).status == Status.FAIL


def test_role_and_count():
    els = [{"label": "Save", "role": "button"},
           {"label": "Name", "role": "textbox"},
           {"label": "Cancel", "role": "button"}]
    assert evaluate_assertion(Assertion(kind=K.ROLE, target="button"), elements=els).status == Status.PASS
    assert evaluate_assertion(Assertion(kind=K.ROLE, target="slider"), elements=els).status == Status.FAIL
    eq2 = Assertion(kind=K.COUNT, target="button", op=Op.EQUALS, expected=2)
    assert evaluate_assertion(eq2, elements=els).status == Status.PASS
    gte3 = Assertion(kind=K.COUNT, target="button", op=Op.GTE, expected=3)
    assert evaluate_assertion(gte3, elements=els).status == Status.FAIL


def test_url():
    a = Assertion(kind=K.URL, target="/settings", op=Op.CONTAINS)
    assert evaluate_assertion(a, url="http://x/settings").status == Status.PASS
    assert evaluate_assertion(a, url="http://x/home").status == Status.FAIL
    assert evaluate_assertion(a, url=None).status == Status.INCONCLUSIVE  # not silently pass


def test_value_and_state():
    states = {"notifications": {"checked": True}, "name": {"value": "Alice"}}
    checked = Assertion(kind=K.STATE, target="checked", on="Notifications", expected="true")
    assert evaluate_assertion(checked, states=states).status == Status.PASS
    val_ok = Assertion(kind=K.VALUE, on="Name", expected="Alice")
    assert evaluate_assertion(val_ok, states=states).status == Status.PASS
    val_bad = Assertion(kind=K.VALUE, on="Name", expected="Bob")
    assert evaluate_assertion(val_bad, states=states).status == Status.FAIL
    missing = Assertion(kind=K.STATE, target="checked", on="Missing")
    assert evaluate_assertion(missing, states=states).status == Status.INCONCLUSIVE


def test_network_and_screenshot_are_inconclusive_not_silent():
    # `network=False` is the historical "no capture here" flag; a surface with no tap
    # must never let an absence check pass on evidence nobody gathered
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api"), network=False).status == Status.INCONCLUSIVE
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api")).status == Status.INCONCLUSIVE
    assert evaluate_assertion(Assertion(kind=K.SCREENSHOT, target="hero"), screenshot=False).status == Status.INCONCLUSIVE


def _req(url, status=None, failed=False, error="", method="GET") -> dict:
    return {"method": method, "url": url, "status": status, "failed": failed, "error": error}


NETWORK = [
    _req("http://app/api/items", 200),
    _req("http://app/api/save", 500, method="POST"),
    _req("http://app/api/upload", failed=True, error="net::ERR_CONNECTION_REFUSED",
         method="POST"),
]


def test_network_checks_the_status_of_the_matching_request():
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/items", expected="ok"),
                              network=NETWORK).status == Status.PASS
    broken = evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/save", expected="ok"),
                                network=NETWORK)
    assert broken.status == Status.FAIL and "500" in str(broken.actual)
    for expected in (500, "500", "5xx"):
        assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/save",
                                            expected=expected),
                                  network=NETWORK).status == Status.PASS


def test_network_target_can_pin_the_method():
    # the write and the read of one route are different requests; only GET /api/items 200'd
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="POST /api/items",
                                        expected="ok"), network=NETWORK).status == Status.FAIL
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="GET /api/items",
                                        expected="ok"), network=NETWORK).status == Status.PASS


def test_network_absent_covers_the_whole_window_when_target_is_empty():
    nothing_5xx = Assertion(kind=K.NETWORK, target="", expected="5xx", op=Op.ABSENT)
    assert evaluate_assertion(nothing_5xx, network=NETWORK).status == Status.FAIL
    assert evaluate_assertion(nothing_5xx,
                              network=[_req("http://app/ok", 200)]).status == Status.PASS


def test_a_request_that_never_completed_matches_failed_and_no_status_code():
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/upload",
                                        expected="failed"),
                              network=NETWORK).status == Status.PASS
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/upload", expected=200),
                              network=NETWORK).status == Status.FAIL


def test_an_empty_capture_is_a_real_answer_not_an_unavailable_channel():
    # the tap ran and saw nothing: that FAILS "the save reached the server" and PASSES
    # "nothing was requested" — collapsing it into inconclusive would lose a real check
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/save"),
                              network=[]).status == Status.FAIL
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api/save", op=Op.ABSENT),
                              network=[]).status == Status.PASS


def test_network_compares_numerically_and_refuses_an_unreadable_expectation():
    at_least_400 = Assertion(kind=K.NETWORK, target="/api", op=Op.GTE, expected=400)
    assert evaluate_assertion(at_least_400, network=NETWORK).status == Status.PASS
    assert evaluate_assertion(at_least_400,
                              network=[_req("http://app/api/x", 200)]).status == Status.FAIL
    junk = evaluate_assertion(Assertion(kind=K.NETWORK, target="/api", expected="whenever"),
                              network=NETWORK)
    assert junk.status == Status.INCONCLUSIVE and "not a status" in junk.evidence


def test_summary_overall_is_worst_case():
    results = evaluate_assertions(
        [Assertion(kind=K.TEXT, target="A"), Assertion(kind=K.NETWORK)], texts=["A"])
    assert summarize(results)["overall"] == "inconclusive"
    results = evaluate_assertions([Assertion(kind=K.TEXT, target="A")], texts=["nope"])
    assert summarize(results)["overall"] == "fail"
    results = evaluate_assertions([Assertion(kind=K.TEXT, target="A")], texts=["A"])
    assert summarize(results)["overall"] == "pass"
