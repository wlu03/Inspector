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


def match_findings(expected: list[dict], findings: list[dict]) -> dict:
    """Score `findings` against the manifest's `expected` bugs. Pure.

    A bug is *detected* if any finding's text contains one of its signatures.
    Precision = findings matching some bug / all findings; recall = bugs detected /
    all bugs. Findings matching no signature are false positives (noise vs the
    manifest — a real-but-unlisted bug also lands here).
    """
    ftexts = [(f, _finding_text(f)) for f in findings]
    matched_finding_ids: set = set()
    per_bug: list[dict] = []
    detected = 0

    for bug in expected:
        sigs = _bug_signatures(bug)
        hits = [f.get("id") for f, txt in ftexts if sigs and any(s in txt for s in sigs)]
        for fid in hits:
            matched_finding_ids.add(fid)
        is_detected = bool(hits)
        detected += int(is_detected)
        per_bug.append({
            "id": bug.get("id"),
            "screen": bug.get("screen"),
            "severity": bug.get("severity"),
            "difficulty": bug.get("difficulty"),
            "detected": is_detected,
            "matching_finding_ids": hits,
        })

    total_expected = len(expected)
    total_findings = len(findings)
    tp = len(matched_finding_ids)
    fp = total_findings - tp
    recall = detected / total_expected if total_expected else 0.0
    precision = tp / total_findings if total_findings else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    unmatched = [f.get("id") for f, _ in ftexts if f.get("id") not in matched_finding_ids]

    return {
        "total_expected": total_expected,
        "detected": detected,
        "missed": total_expected - detected,
        "total_findings": total_findings,
        "true_positives": tp,
        "false_positives": fp,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "per_bug": per_bug,
        "unmatched_finding_ids": unmatched,
    }


def run_and_score(repo_path: str, surface: str | None = None, max_steps: int | None = None) -> dict:
    """Live: run `test_app` against a fixture and score the findings it produced."""
    import asyncio

    from fastmcp import Client

    from . import server as srv

    manifest = load_manifest(repo_path)
    expected = manifest.get("bugs", [])
    surface = surface or manifest.get("surface")

    async def _run() -> dict:
        async with Client(srv.mcp) as client:
            args: dict = {"repo_path": repo_path, "goal": "exercise every flow and find bugs"}
            if surface:
                args["surface"] = surface
            if max_steps:
                args["max_steps"] = max_steps
            r = await client.call_tool("test_app", args)
            return getattr(r, "structured_content", None) or getattr(r, "data", None) or {}

    result = asyncio.run(_run())
    report = match_findings(expected, result.get("findings", []))
    report["fixture"] = manifest.get("app", os.path.basename(repo_path.rstrip("/")))
    report["surface"] = result.get("surface", surface)
    report["ready"] = result.get("ready")
    report["stop_reason"] = result.get("stop_reason")
    report["session_id"] = result.get("session_id")
    report["replay"] = result.get("replay")
    return report
