from inspector.audit import audit_to_findings
from inspector.models import Severity


def test_audit_to_findings_maps_axe_images_and_labels():
    audit = {
        "axe_violations": [
            {"id": "color-contrast", "impact": "serious",
             "help": "Elements must have sufficient color contrast", "nodes": 3},
            {"id": "image-alt", "impact": "critical",
             "help": "Images must have alternate text", "nodes": 1},
        ],
        "broken_images": ["http://x/a.png", "http://x/b.png"],
        "unlabeled_inputs": ["email", "search"],
    }
    findings = audit_to_findings(audit, session_id="s", trace_id="t")

    # 2 axe violations + 1 broken-images + 1 form-labels finding
    assert len(findings) == 4
    by_area = {f.suspected_area: f for f in findings}
    assert by_area["axe:color-contrast"].severity == Severity.HIGH
    assert by_area["axe:image-alt"].severity == Severity.CRITICAL
    assert by_area["broken-images"].severity == Severity.MEDIUM
    assert by_area["form-labels"].severity == Severity.MEDIUM
    # session/trace are threaded onto each finding
    assert all(f.session_id == "s" and f.trace_id == "t" for f in findings)


def test_audit_to_findings_empty_audit_yields_nothing():
    assert audit_to_findings({}) == []
    assert audit_to_findings({"axe_violations": [], "broken_images": []}) == []


def test_audit_to_findings_tolerates_malformed_entries():
    audit = {"axe_violations": ["not-a-dict", {"id": "x"}], "broken_images": [None, ""]}
    findings = audit_to_findings(audit)
    # the one valid (if sparse) violation is kept; junk image entries are dropped
    assert len(findings) == 1
    assert findings[0].suspected_area == "axe:x"
