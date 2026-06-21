"""Cartographer data model: Region (a bounded part of the UI), Hypothesis (a
falsifiable claim about a control), and Candidate (a measured oracle violation)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


def norm(label: str) -> str:
    """Normalize a label for matching/hashing (mirrors expectations._norm)."""
    return re.sub(r"\s+", " ", (label or "").strip().lower())


@dataclass
class Region:
    """A bounded part of the UI — a cluster of elements an agent inspects in depth."""

    region_id: str
    title: str
    bbox: list[float]          # [x1, y1, x2, y2] ratios 0..1 (union of members)
    member_ids: list[int]
    role_class: str = "panel"  # nav | form | list | panel | header | toolbar | modal

    @staticmethod
    def make(title: str, bbox: list[float], member_ids: list[int],
             role_class: str = "panel", labels: list[str] | None = None) -> "Region":
        # stable across observations AND builds: same controls -> same id.
        key = role_class + "|" + "|".join(sorted(norm(x) for x in (labels or [])))
        rid = "rgn_" + hashlib.sha1(key.encode()).hexdigest()[:8]
        return Region(rid, title, bbox, member_ids, role_class)


@dataclass
class Hypothesis:
    """A falsifiable claim bound to ONE control in a region, with a named oracle."""

    lens: str                  # "logic_arithmetic" | "state_sync"
    region_id: str
    target_label: str
    expected: str              # human-readable expected behavior (infer-first)
    meta: dict = field(default_factory=dict)


@dataclass
class Candidate:
    """A measured oracle violation — a bug candidate (pre-verification)."""

    lens: str
    region_id: str
    issue: str
    expected: str
    actual: str
    severity: str
    bbox: list[float]
    evidence: dict = field(default_factory=dict)
    suggested_fix: str = ""
