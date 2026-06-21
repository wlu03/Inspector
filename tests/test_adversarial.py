from inspector.adversarial import (
    EDGE_INPUTS,
    PATTERNS,
    adversarial_value,
    catalog_text,
)
from inspector.driver import HeuristicDriver
from inspector.models import Element


def test_adversarial_value_cycles_through_payloads():
    n = len(EDGE_INPUTS)
    assert adversarial_value(0) == EDGE_INPUTS[0]
    assert adversarial_value(n) == EDGE_INPUTS[0]      # wraps around
    assert adversarial_value(n + 2) == EDGE_INPUTS[2]


def test_edge_inputs_include_the_classic_breakers():
    payloads = [p for _, p in EDGE_INPUTS]
    assert "" in payloads                               # empty submit
    assert any("<script>" in p for p in payloads)       # XSS
    assert any(len(p) >= 500 for p in payloads)         # overflow


def test_catalog_text_covers_core_features_and_intent():
    txt = catalog_text().lower()
    for feature in ("forms", "modals", "navigation", "accessibility"):
        assert feature in txt
    # adversarial intent, not happy-path confirmation
    assert "escape" in txt and "double-click" in txt
    assert "axe-core" in txt


def test_patterns_are_nonempty_lists():
    assert PATTERNS
    assert all(isinstance(v, list) and v for v in PATTERNS.values())


def _field(eid: int, label: str, y: float) -> Element:
    return Element(
        id=eid, label=label, role="text",
        bbox=[0.1, y, 0.2, y + 0.05], interactivity=True,
    )


def test_heuristic_driver_pushes_distinct_adversarial_inputs_per_field():
    driver = HeuristicDriver()
    f1, f2 = _field(1, "Email", 0.1), _field(2, "Name", 0.3)

    d1 = driver.decide(b"", [f1], "goal", [], [])
    assert d1.action == "type" and d1.target_id == 1

    # second, distinct field → next payload in the cycle (not the same benign string)
    d2 = driver.decide(b"", [f1, f2], "goal", [], [])
    assert d2.action == "type" and d2.target_id == 2
    assert d1.text != d2.text
