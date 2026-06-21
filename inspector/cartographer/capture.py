"""Combined grounding for the oracles: interactive elements (for act/control_state)
+ non-interactive displayed text (for READING values). Text ids are offset above the
interactive ids so they never collide and interactive ids stay stable for control_state."""

from __future__ import annotations

from ..models import Element


def capture(session) -> list[Element]:
    interactive = list(session.last_elements or [])
    offset = max((e.id for e in interactive), default=-1) + 1
    text: list[Element] = []
    fn = getattr(session.adapter, "text_elements", None)
    if fn is not None:
        try:
            for t in (fn() or []):
                text.append(t.model_copy(update={"id": t.id + offset}))
        except Exception:
            pass
    return interactive + text
