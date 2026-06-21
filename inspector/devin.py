"""Devin AI auto-fix integration: hand a Bug Ledger finding to Devin → it opens a PR.

Inspector → Devin direction (the "Fix with Devin" button). Uses Devin's v1 API
(POST /v1/sessions to start, GET /v1/session/{id} to poll for the PR) over stdlib
urllib — no new dependency. The pure helpers (prompt + payload + PR extraction) are
unit-testable without the network; the orchestrators read/patch the trace findings.

Research: Devin is also an MCP *client* — it can add Inspector as a custom MCP server
(Settings → Connections → MCP, HTTP/SSE transport) and call test_app/get_findings to
verify its own fix. That requires running Inspector over HTTP (it's stdio by default).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request

from .dashboard.aggregate import (
    bug_ledger,
    findings_for_signature,
    fix_prompt,
    patch_finding,
)


def github_repo(repo_path: str | None = None) -> str | None:
    """The GitHub 'owner/name' from the repo's git remote — Devin clones from GitHub,
    not the local path, so the prompt must name it. Returns None if no GitHub remote."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_path or ".", "remote", "-v"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    for line in (r.stdout or "").splitlines():
        m = re.search(r"github\.com[:/]([\w.\-]+/[\w.\-]+?)(?:\.git)?(?:\s|$)", line)
        if m:
            return m.group(1)
    return None


# Surface → where the code lives + how the runtime state maps back to source, so Devin
# can locate the fix even when 'Suspected location' is a behavioural description.
_SOURCE_HINT = {
    "ios": "SwiftUI/Swift files (*.swift) — on-screen text is a Text's content, a "
           "field's typed value is its @State/binding, and views carry accessibilityIdentifier",
    "android": "Kotlin/Java + layout XML (*.kt, *.java, *.xml)",
    "web": "JS/TS + HTML/JSX (*.js, *.ts, *.tsx, *.jsx, *.html)",
    "electron": "the renderer JS/HTML and the main process (*.js, *.html, *.ts)",
}


def build_fix_prompt(
    finding: dict, repo_path: str, surface: str = "", repo: str | None = None
) -> str:
    """Devin task prompt for one finding — enough context to LOCATE, fix, and open a PR.

    `repo` pins the target GitHub 'owner/name' (so every PR lands on our repo); when
    omitted it falls back to the app-under-test's own git remote.
    """
    base = fix_prompt(finding, {"repo_path": repo_path, "surface": surface})
    repo = repo or github_repo(repo_path)
    where = (f"In the GitHub repository **{repo}**" if repo
             else "In the repository above")
    rel = ""
    if repo and repo_path and os.path.isdir(repo_path):
        try:
            root = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if root:
                rel = os.path.relpath(repo_path, root)
        except Exception:
            rel = ""
    area = f"`{rel}/`" if rel and rel != "." else "the repository"
    hint = _SOURCE_HINT.get((surface or "").lower(), "the application source")
    return (
        base
        + f"\n\n{where} — the affected app is under {area}.\n"
        "LOCATING THE CODE: the 'Suspected location' above may be a behavioural "
        f"description, not a file path. Find the code by grepping {area} for the exact "
        "on-screen text, labels, and identifiers quoted in What's wrong / Expected / "
        f"Actual ({hint}).\n"
        "THEN: implement a minimal, focused fix for the ROOT CAUSE; build and run the "
        "project's tests; and OPEN A PULL REQUEST with a clear title and a description "
        "that states the bug (severity, expected vs actual), the fix, and how you "
        "verified it. Keep the diff minimal — do not refactor unrelated code or modify "
        "example/test fixtures beyond the fix."
    )


def build_create_payload(prompt: str, title: str, max_acu: int | None) -> dict:
    """The POST /v1/sessions body. Pure."""
    payload: dict = {"prompt": prompt, "idempotent": True, "title": title[:120]}
    if max_acu:
        payload["max_acu_limit"] = max_acu
    return payload


def extract_pr_url(session_data: dict) -> str | None:
    """Pull a PR URL out of a Devin session payload, defensively across shapes."""
    if not isinstance(session_data, dict):
        return None
    pr = session_data.get("pull_request")
    if isinstance(pr, dict) and pr.get("url"):
        return pr["url"]
    if isinstance(pr, str) and pr.startswith("http"):
        return pr
    for key in ("pull_request_url", "pr_url"):
        if session_data.get(key):
            return session_data[key]
    out = session_data.get("structured_output")
    if isinstance(out, dict):
        for v in out.values():
            if isinstance(v, str) and "github.com" in v and "/pull/" in v:
                return v
    return None


def _api(cfg, method: str, path: str, payload: dict | None = None) -> dict:
    """One Devin REST call (stdlib urllib). Raises on transport/HTTP error."""
    url = cfg.devin_base_url.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {cfg.devin_api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else {}


def fix_with_devin(cfg, trace_root: str, signature: str, _api_fn=_api) -> dict:
    """Start a Devin session to fix the issue `signature`; tag its findings 'fixing'.

    Picks the most recent occurrence of the signature for context, asks Devin to open a
    PR, and writes the Devin session URL + status='fixing' onto every matching finding
    file so the ledger reflects it. `_api_fn` is injectable for tests.
    """
    if not cfg.devin_api_key:
        return {"error": "DEVIN_API_KEY not set — add it to enable the Fix with Devin button"}

    matches = findings_for_signature(trace_root, signature)
    if not matches:
        return {"error": f"no finding matches signature {signature!r}"}

    latest = matches[0]
    finding, repo = latest["data"], latest["repo_path"]
    prompt = build_fix_prompt(
        finding, repo, finding.get("_surface", ""), repo=getattr(cfg, "devin_repo", None)
    )
    title = f"Fix: {finding.get('summary', 'bug')}"[:120]

    try:
        resp = _api_fn(cfg, "POST", "/v1/sessions",
                       build_create_payload(prompt, title, cfg.devin_max_acu))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Devin API call failed: {str(exc)[:200]}"}

    devin_url = resp.get("url", "")
    devin_session_id = resp.get("session_id", "")
    for m in matches:  # mark every occurrence so any run's view shows it
        patch_finding(m["path"], {
            "status": "fixing", "devin_url": devin_url,
            "devin_session_id": devin_session_id,
        })
    return {
        "signature": signature, "repo_path": repo,
        "devin_session_id": devin_session_id, "devin_url": devin_url,
        "status": "fixing",
        "note": "Devin is working on a PR. Poll devin_status, or re-run test_app after "
                "the PR merges — the issue auto-verifies when it no longer reproduces.",
    }


def poll_devin(cfg, trace_root: str, devin_session_id: str, _api_fn=_api) -> dict:
    """Check a Devin session once; if it opened a PR, record pr_url on the findings."""
    if not cfg.devin_api_key:
        return {"error": "DEVIN_API_KEY not set"}
    try:
        data = _api_fn(cfg, "GET", f"/v1/session/{devin_session_id}")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Devin API call failed: {str(exc)[:200]}"}

    pr_url = extract_pr_url(data)
    status = data.get("status_enum") or data.get("status") or "running"
    if pr_url:
        # find the signature these findings belong to via the session id we stamped
        for g in bug_ledger(trace_root):
            for m in findings_for_signature(trace_root, g["signature"]):
                if m["data"].get("devin_session_id") == devin_session_id:
                    patch_finding(m["path"], {"pr_url": pr_url})
    return {"devin_session_id": devin_session_id, "status": status, "pr_url": pr_url}
