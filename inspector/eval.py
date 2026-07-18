"""Bug-scoring eval harness — the objective "does Inspector work?" gate.

Each fixture ships a `bugs.json` manifest whose bugs carry `log_signature` /
`crash_signature` strings. We run Inspector against the fixture, then match the
findings it produced against those signatures to compute precision / recall / F1.

`match_findings` is pure (unit-tested without a sandbox); `run_and_score` does the
live run via the in-memory MCP client.
"""

from __future__ import annotations

import json
import os


def load_manifest(repo_path: str) -> dict:
    """Load a fixture's bugs.json (the expected-bug manifest)."""
    with open(os.path.join(repo_path, "bugs.json")) as f:
        return json.load(f)


def _bug_signatures(bug: dict) -> list[str]:
    sigs = []
    for key in ("log_signature", "crash_signature"):
        val = bug.get(key)
        if val:
            sigs.append(str(val).lower())
    return sigs


def _finding_text(f: dict) -> str:
    """All the text of a finding we'll match signatures against."""
    parts = [
        str(f.get("summary", "")),
        str(f.get("actual", "")),
        str(f.get("expected", "")),
        str(f.get("suspected_area", "")),
    ]
    parts += [str(x) for x in (f.get("logs") or [])]
    return " ".join(parts).lower()


def _max_matching(edges: dict[int, set[int]]) -> dict[int, int]:
    """Maximum bipartite matching (Kuhn's augmenting paths).

    `edges` maps a bug index to the finding indices it could match. Returns a
    {finding_index: bug_index} map with each finding matched to at most one bug and
    each bug to at most one finding, so neither recall nor precision can double-count.
    """
    finding_to_bug: dict[int, int] = {}

    def augment(bug: int, seen: set[int]) -> bool:
        for f in sorted(edges.get(bug, ())):
            if f in seen:
                continue
            seen.add(f)
            if f not in finding_to_bug or augment(finding_to_bug[f], seen):
                finding_to_bug[f] = bug
                return True
        return False

    for bug in sorted(edges):
        augment(bug, set())
    return finding_to_bug


def _score(expected: list[dict], findings: list[dict], edges: dict[int, set[int]],
           extra: dict | None = None) -> dict:
    """Precision / recall / F1 from a one-to-one matching of bugs to findings."""
    finding_to_bug = _max_matching(edges)
    bug_to_finding = {b: f for f, b in finding_to_bug.items()}
    fids = [f.get("id") for f in findings]

    detected = 0
    per_bug: list[dict] = []
    for i, bug in enumerate(expected):
        mf = bug_to_finding.get(i)
        is_detected = mf is not None
        detected += int(is_detected)
        per_bug.append({
            "id": bug.get("id"), "screen": bug.get("screen"),
            "severity": bug.get("severity"), "difficulty": bug.get("difficulty"),
            "detected": is_detected,
            "matching_finding_ids": [fids[mf]] if is_detected else [],
        })

    total_expected, total_findings = len(expected), len(findings)
    tp = len(finding_to_bug)  # == detected under a one-to-one matching
    matched = {fids[f] for f in finding_to_bug}
    recall = detected / total_expected if total_expected else 0.0
    precision = tp / total_findings if total_findings else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    report = {
        "total_expected": total_expected,
        "detected": detected,
        "missed": total_expected - detected,
        "total_findings": total_findings,
        "true_positives": tp,
        "false_positives": total_findings - tp,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "per_bug": per_bug,
        "unmatched_finding_ids": [fid for fid in fids if fid not in matched],
    }
    if extra:
        report.update(extra)
    return report


def match_findings(expected: list[dict], findings: list[dict]) -> dict:
    """Score `findings` against the manifest's `expected` bugs. Pure.

    A bug can be matched by any finding whose text contains one of its signatures, then
    a maximum one-to-one matching is taken: a broad finding cannot inflate recall across
    several bugs, and a duplicate finding for one bug counts as a false positive.
    Precision = matched findings / all findings; recall = matched bugs / all bugs.
    """
    ftexts = [_finding_text(f) for f in findings]
    edges: dict[int, set[int]] = {}
    for i, bug in enumerate(expected):
        sigs = _bug_signatures(bug)
        if not sigs:
            continue
        cand = {j for j, txt in enumerate(ftexts) if any(s in txt for s in sigs)}
        if cand:
            edges[i] = cand
    return _score(expected, findings, edges)


def match_findings_semantic(expected: list[dict], findings: list[dict], mapping: dict) -> dict:
    """Score findings against bugs using a precomputed {bug_id: [finding_ids]} map. Pure.

    For log-free fixtures (subtle UI-state bugs), a bug is *detected* when the agent's
    natural-language finding semantically reports it, judged by an LLM (`mapping`), not
    a greppable signature. The mapping's edges are resolved by the same one-to-one
    matching so the metrics line up with `match_findings`.
    """
    idx = {f.get("id"): j for j, f in enumerate(findings)}
    edges: dict[int, set[int]] = {}
    for i, bug in enumerate(expected):
        cand = {idx[fid] for fid in mapping.get(bug.get("id"), []) if fid in idx}
        if cand:
            edges[i] = cand
    return _score(expected, findings, edges, extra={"scoring": "semantic"})


def _bug_for_judge(bug: dict) -> dict:
    """Normalize a manifest bug for the semantic judge, tolerating both fixture styles
    (title/description/expected_finding OR summary/oracle/repro)."""
    return {
        "id": bug.get("id"),
        "title": bug.get("title") or bug.get("summary"),
        "what_is_wrong": bug.get("description") or bug.get("summary"),
        "expected_finding": bug.get("expected_finding") or bug.get("oracle"),
        "screen": bug.get("screen"),
        "repro": bug.get("repro"),
    }


def _semantic_mapping(expected: list[dict], findings: list[dict], config) -> dict:
    """Ask Claude which findings report which bugs → {bug_id: [finding_ids]}.

    The judge sees only the bug DESCRIPTIONS and the agent's findings (never the
    fixture source), so it scores whether the agent actually perceived each defect.
    """
    import json as _json

    import anthropic

    bugs = [_bug_for_judge(b) for b in expected]
    finds = [{"id": f.get("id"), "summary": f.get("summary"), "detail": f.get("actual"),
              "area": f.get("suspected_area")} for f in findings]
    prompt = (
        "You score a UI-testing agent. Below are EXPECTED bugs (each a subtle UI defect) and "
        "the agent's FINDINGS. For each bug, list the ids of findings that genuinely report THAT "
        "bug (same defect/behavior — not merely the same screen or a vague 'looks off'). A finding "
        "may match at most one bug; many findings match none. Be strict.\n\n"
        f"EXPECTED_BUGS:\n{_json.dumps(bugs, indent=2)}\n\n"
        f"FINDINGS:\n{_json.dumps(finds, indent=2)}\n\n"
        'Respond with ONLY JSON: {"matches": {"BUG-01": ["fnd_x"], "BUG-02": [], ...}}'
    )
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    msg = client.messages.create(
        model=config.driver_model, max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content)
    start, end = text.find("{"), text.rfind("}")
    data = _json.loads(text[start:end + 1])
    raw = data.get("matches", data)
    return {k: list(v or []) for k, v in raw.items()}


def _tool_args(tool: str, repo_path: str, surface: str | None = None,
               max_steps: int | None = None) -> dict:
    """Build the call_tool args for the system under test (test_app or test_feature)."""
    args: dict = {"repo_path": repo_path}
    if tool == "test_feature":
        if max_steps:
            args["max_regions"] = max_steps
    else:  # test_app autopilot
        args["goal"] = "exercise every flow and find bugs"
        if max_steps:
            args["max_steps"] = max_steps
    if surface:
        args["surface"] = surface
    return args


def run_and_score(repo_path: str, surface: str | None = None, max_steps: int | None = None,
                  tool: str = "test_app") -> dict:
    """Live: run the system under test (`tool`) against a fixture and score its findings.

    `tool` selects what is measured: "test_app" (the LLM autopilot) or "test_feature"
    (the deterministic Cartographer). The chosen tool is recorded in the report as
    `scored_tool`, so results say which system produced them.
    """
    import asyncio

    from fastmcp import Client

    from . import server as srv

    manifest = load_manifest(repo_path)
    expected = manifest.get("bugs", [])
    surface = surface or manifest.get("surface")

    async def _run() -> dict:
        async with Client(srv.mcp) as client:
            r = await client.call_tool(tool, _tool_args(tool, repo_path, surface, max_steps))
            return getattr(r, "structured_content", None) or getattr(r, "data", None) or {}

    result = asyncio.run(_run())
    found = result.get("findings", [])
    if manifest.get("scoring") == "semantic":
        # log-free fixture: an LLM judges findings ↔ bug descriptions.
        from .config import Config
        try:
            mapping = _semantic_mapping(expected, found, Config.from_env())
            report = match_findings_semantic(expected, found, mapping)
        except Exception as exc:  # fall back to log matcher, but surface why
            report = match_findings(expected, found)
            report["semantic_error"] = f"{type(exc).__name__}: {exc}"
    else:
        report = match_findings(expected, found)
    report["fixture"] = manifest.get("app", os.path.basename(repo_path.rstrip("/")))
    report["scored_tool"] = tool
    report["surface"] = result.get("surface", surface)
    report["ready"] = result.get("ready")
    report["stop_reason"] = result.get("stop_reason")
    report["session_id"] = result.get("session_id")
    report["replay"] = result.get("replay")
    return report
