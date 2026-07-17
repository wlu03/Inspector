"""Path-safety helpers shared across the server.

Session/trace/finding ids arrive from tool callers and the dashboard POST handler and
are joined onto the trace root, and repo paths are handed to adapters/subprocesses —
so both must be validated before they touch the filesystem.
"""

from __future__ import annotations

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
