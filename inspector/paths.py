"""Path-safety helpers shared across the server.

Session/trace/finding ids arrive from tool callers and the dashboard POST handler and
are joined onto the trace root, and repo paths are handed to adapters/subprocesses —
so both must be validated before they touch the filesystem.
"""

from __future__ import annotations

import hashlib
import os
import re

# A safe single path segment: starts alphanumeric, then alnum/_/-, no separators or dots
# (so "..", "/", "\" and absolute paths are all rejected). Covers ses_/trc_/finding ids.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def valid_id(value: object) -> bool:
    """True if `value` is safe to use as a single path segment (no traversal)."""
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def safe_repo_path(repo_path: str, workspace_roots: list[str] | None = None) -> str:
    """Canonicalize `repo_path`; if `workspace_roots` is non-empty, require it under one.

    Default (no roots) preserves current behavior but still resolves symlinks/relative
    segments. Raises PermissionError when a roots allowlist is configured and the path
    escapes it.
    """
    rp = os.path.realpath(os.path.expanduser(repo_path))
    roots = [os.path.realpath(os.path.expanduser(r)) for r in (workspace_roots or []) if r]
    if roots:
        for r in roots:
            if rp == r or rp.startswith(r + os.sep):
                return rp
        raise PermissionError(
            f"repo_path {repo_path!r} is outside the allowed INSPECTOR_WORKSPACE_ROOTS"
        )
    return rp


def repo_key(repo_path: str, workspace_roots: list[str] | None = None) -> str:
    """A stable, safe single path segment naming one repo, for its per-repo artifacts.

    Saved test plans are filed per repo, and the repo path comes from the caller, so it
    can never be joined onto the trace root as it arrived: it is absolute, it may contain
    `..`, and on a server with a workspace allowlist it may not be ours to touch at all.
    `safe_repo_path` is the one place that judgment lives, so this goes through it and
    then names the directory after what came back — the canonical basename (so a listing
    is readable) plus a digest of the whole canonical path (so two checkouts of the same
    project, or a repo that was later renamed, never share a plan set).
    """
    rp = safe_repo_path(repo_path, workspace_roots)
    slug = re.sub(r"[^A-Za-z0-9_-]", "-", os.path.basename(rp.rstrip(os.sep)))[:40].strip("-_")
    digest = hashlib.sha256(rp.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{slug}-{digest}" if slug else digest


def plans_root(trace_root: str) -> str:
    """Where every repo's saved plans live: `<trace_root>/plans/`.

    Beside the session directories and the saved-state files rather than inside any one
    session, because a plan outlives the run that wrote it — that is the entire point of
    persisting it.
    """
    return os.path.join(trace_root, "plans")


def plans_dir(trace_root: str, repo_path: str, workspace_roots: list[str] | None = None) -> str:
    """The directory holding one repo's saved plans."""
    return os.path.join(plans_root(trace_root), repo_key(repo_path, workspace_roots))


def plan_file(
    trace_root: str, repo_path: str, plan_id: str,
    workspace_roots: list[str] | None = None,
) -> str:
    """One saved plan's file. Raises ValueError when `plan_id` isn't a safe segment."""
    if not valid_id(plan_id):
        raise ValueError(f"invalid plan id {plan_id!r}: letters, digits, '_' and '-' only")
    return os.path.join(plans_dir(trace_root, repo_path, workspace_roots), f"{plan_id}.json")
