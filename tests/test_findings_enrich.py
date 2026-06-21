from inspector.detection import extract_location, finding_signature, scan_logs
from inspector.models import Severity

# the exact lines Inspector captured live from the buggy Save click
LINES = [
    "[console.error] query not invalidated after save",
    "[exception] TypeError: Cannot read properties of undefined (reading 'show')",
    "    at HTMLButtonElement.<anonymous> (http://localhost:5173/main.js:8:10)",
]


def test_extract_location():
    assert extract_location("at foo (http://localhost:5173/main.js:8:10)") == "main.js:8"
    assert extract_location("at App.onClick(MainActivity.java:42)") == "MainActivity.java:42"
    assert extract_location("[exception] TypeError: nope") is None


def test_scan_pulls_location_and_skips_frames():
    findings = scan_logs(LINES, "ses", "trc")
    # the bare 'at ...' stack frame is not its own finding
    assert all(not f.summary.strip().lower().startswith("at ") for f in findings)
    # the source location is attached (looked ahead from the stack frame)
    assert "main.js:8" in {f.suspected_area for f in findings}
    # the TypeError is flagged HIGH
    assert Severity.HIGH in {f.severity for f in findings}


def test_dedup_signature_stable():
    a = scan_logs(LINES)
    b = scan_logs(LINES)
    assert finding_signature(a[0]) == finding_signature(b[0])
