from inspector.eval import _tool_args, match_findings, match_findings_semantic

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


def test_semantic_matcher_scores_from_mapping():
    # log-free bugs: the LLM judge mapping decides detection, not signatures.
    findings = [_f("fnd_a", "field went blank after returning"), _f("fnd_b", "noise"),
                _f("fnd_c", "counter undercounts")]
    mapping = {"BUG-01": ["fnd_a"], "BUG-02": [], "BUG-03": ["fnd_c"]}
    r = match_findings_semantic(EXPECTED, findings, mapping)
    assert r["detected"] == 2 and r["recall"] == round(2 / 3, 3)
    assert r["true_positives"] == 2 and r["false_positives"] == 1  # fnd_b matched nothing
    assert r["scoring"] == "semantic"
    by_id = {b["id"]: b for b in r["per_bug"]}
    assert by_id["BUG-01"]["detected"] and not by_id["BUG-02"]["detected"]


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
        _f("f2", summary="query not invalidated after save"),  # also BUG-01 (redundant)
        _f("f3", summary="Failed to load resource: 404"),  # noise
    ]
    r = match_findings(EXPECTED, findings)
    assert r["detected"] == 1                      # BUG-01 counted once
    assert r["recall"] == round(1 / 3, 3)
    assert r["true_positives"] == 1                # one-to-one: one finding credited per bug
    assert r["false_positives"] == 2               # the redundant BUG-01 finding + noise
    assert "f3" in r["unmatched_finding_ids"] and "f2" in r["unmatched_finding_ids"]


def test_no_findings_zero_recall():
    r = match_findings(EXPECTED, [])
    assert r["recall"] == 0.0 and r["precision"] == 0.0 and r["missed"] == 3


def test_case_insensitive():
    r = match_findings([EXPECTED[1]], [_f("f", actual="TOGGLE STATE DESYNC")])
    assert r["detected"] == 1


def test_tool_args_selects_autopilot_or_cartographer():
    a = _tool_args("test_app", "/repo", surface="web", max_steps=5)
    assert a["repo_path"] == "/repo" and a["surface"] == "web"
    assert a["max_steps"] == 5 and "goal" in a and "max_regions" not in a
    c = _tool_args("test_feature", "/repo", max_steps=8)
    assert c["max_regions"] == 8 and "goal" not in c and "max_steps" not in c
