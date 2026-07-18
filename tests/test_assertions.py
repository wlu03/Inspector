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
    assert evaluate_assertion(Assertion(kind=K.NETWORK, target="/api"), network=False).status == Status.INCONCLUSIVE
    assert evaluate_assertion(Assertion(kind=K.SCREENSHOT, target="hero"), screenshot=False).status == Status.INCONCLUSIVE


def test_summary_overall_is_worst_case():
    results = evaluate_assertions(
        [Assertion(kind=K.TEXT, target="A"), Assertion(kind=K.NETWORK)], texts=["A"])
    assert summarize(results)["overall"] == "inconclusive"
    results = evaluate_assertions([Assertion(kind=K.TEXT, target="A")], texts=["nope"])
    assert summarize(results)["overall"] == "fail"
    results = evaluate_assertions([Assertion(kind=K.TEXT, target="A")], texts=["A"])
    assert summarize(results)["overall"] == "pass"
