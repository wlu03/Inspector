"""The missing-element oracle must not flag a whole nav on a blank/transitional frame."""
from __future__ import annotations

from inspector.expectations import ExpectedElement, check_expectations


class _Trace:
    def __init__(self):
        self.saved = []

    def save_finding(self, f):
        self.saved.append(f)


class _Rec:
    id = "s"
    trace_id = "t"

    def __init__(self):
        self.findings = []


class _Sess:
    def __init__(self, rendered):
        self.adapter = type("A", (), {
            "rendered_elements": lambda self: rendered,
            "screenshot": lambda self: b"",
        })()
        self.trace = _Trace()
        self.record = _Rec()


def _expected(n):
    return [ExpectedElement(label=f"Item{i}", kind="link", source_ref=f"src:{i}") for i in range(n)]


_FLAG_ALL = lambda c, a, s: {"is_bug": True, "severity": "high"}  # noqa: E731


def test_guard_skips_blank_frame():
    out = check_expectations(_Sess([]), _expected(9), _FLAG_ALL)
    assert out == []   # nothing rendered → don't flag the whole nav


def test_guard_skips_mostly_missing_frame():
    out = check_expectations(_Sess(["Item0", "Item1"]), _expected(9), _FLAG_ALL)
    assert out == []   # only 2/9 present → bad frame, not 7 real bugs


def test_flags_single_real_miss_with_solid_baseline():
    exp = _expected(9)
    s = _Sess([e.label for e in exp[:8]])   # 8 present, 1 genuinely missing
    out = check_expectations(s, exp, _FLAG_ALL)
    assert len(out) == 1 and "Item8" in out[0].summary
