"""Deterministic UI segmentation: cluster Element[] into bounded Regions.

Phase 0 uses spatial connected-components over the normalized bboxes (no LLM): two
elements join the same region if their bboxes are near in BOTH axes (adjacent /
overlapping). A counter display + its +/Reset buttons cluster into one panel; a
toggle + its label into another. (Phase 4 swaps in CDP-landmark / AX-container
segmentation for higher fidelity — see docs/15 §2.)
"""

from __future__ import annotations

from ..models import Element
from .models import Region

_GAP = 0.06          # max bbox gap (ratio of viewport) for two elements to join a region
_FORM_ROLES = {"input", "textfield", "textarea", "select", "combobox"}
_NAV_ROLES = {"link", "tab", "a"}


def _gaps(a: list[float], b: list[float]) -> tuple[float, float]:
    hgap = max(0.0, a[0] - b[2], b[0] - a[2])
    vgap = max(0.0, a[1] - b[3], b[1] - a[3])
    return hgap, vgap


def _union_bbox(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _role_class(members: list[Element]) -> str:
    roles = {(m.role or "").lower() for m in members}
    if roles & _FORM_ROLES:
        return "form"
    if roles & _NAV_ROLES and sum(1 for m in members if (m.role or "").lower() in _NAV_ROLES) >= 2:
        return "nav"
    return "panel"


def _title(members: list[Element]) -> str:
    # top-most non-interactive text, else top-most label.
    texts = sorted((m for m in members if m.label), key=lambda m: m.bbox[1])
    static = [m for m in texts if not m.interactivity]
    return (static[0].label if static else (texts[0].label if texts else ""))[:60]


def segment(elements: list[Element]) -> list[Region]:
    els = [e for e in elements if e.bbox and len(e.bbox) == 4]
    n = len(els)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    for i in range(n):
        for j in range(i + 1, n):
            hg, vg = _gaps(els[i].bbox, els[j].bbox)
            if hg <= _GAP and vg <= _GAP:
                union(i, j)

    comps: dict[int, list[Element]] = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(els[i])

    regions: list[Region] = []
    for members in comps.values():
        bbox = _union_bbox([m.bbox for m in members])
        labels = [m.label for m in members if m.label]
        regions.append(Region.make(_title(members), bbox, [m.id for m in members],
                                    _role_class(members), labels))
    # rank by interactive density — the parts most worth investigating first.
    interactive = {m.id for m in els if m.interactivity}
    regions.sort(key=lambda r: -sum(1 for mid in r.member_ids if mid in interactive))
    return regions
