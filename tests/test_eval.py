from inspector.eval import match_findings

# real signatures from the fixture manifests
EXPECTED = [
    {"id": "BUG-01", "screen": "Settings", "severity": "critical", "difficulty": "obvious",
     "log_signature": "query not invalidated after save",
     "crash_signature": "TypeError: Cannot read properties of undefined (reading 'show')"},
    {"id": "BUG-02", "screen": "Settings", "severity": "low", "difficulty": "subtle",
     "log_signature": "toggle state desync", "crash_signature": None},
    {"id": "BUG-03", "screen": "Profile", "severity": "high", "difficulty": "subtle",
     "log_signature": "validation skipped on submit", "crash_signature": None},
]


def _f(fid, summary="", actual="", logs=None):
    return {"id": fid, "summary": summary, "actual": actual, "logs": logs or []}


def test_perfect_recall_and_precision():
    findings = [
        _f("f1", actual="query not invalidated after save"),
        _f("f2", summary="toggle state desync detected"),
        _f("f3", logs=["validation skipped on submit"]),
    ]
    r = match_findings(EXPECTED, findings)
    assert r["recall"] == 1.0 and r["precision"] == 1.0
    assert r["detected"] == 3 and r["false_positives"] == 0


def test_two_findings_one_bug_plus_false_positive():
    findings = [
        _f("f1", actual="TypeError: Cannot read properties of undefined (reading 'show')"),  # BUG-01
        _f("f2", summary="query not invalidated after save"),  # BUG-01 again
        _f("f3", summary="Failed to load resource: 404"),  # noise
    ]
    r = match_findings(EXPECTED, findings)
    assert r["detected"] == 1                      # BUG-01 counted once
    assert r["recall"] == round(1 / 3, 3)
    assert r["true_positives"] == 2                # both real-bug findings
    assert r["false_positives"] == 1
    assert "f3" in r["unmatched_finding_ids"]


def test_no_findings_zero_recall():
    r = match_findings(EXPECTED, [])
    assert r["recall"] == 0.0 and r["precision"] == 0.0 and r["missed"] == 3


def test_case_insensitive():
    r = match_findings([EXPECTED[1]], [_f("f", actual="TOGGLE STATE DESYNC")])
    assert r["detected"] == 1
