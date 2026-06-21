from __future__ import annotations

# "Try to break it" input payloads — the adversarial values to push through any
# text field. Ordered roughly benign->nasty; an explorer cycles through them across
# fields so a SINGLE pass exercises empties, injection, overflow, and unicode
# instead of typing the same harmless string everywhere.
EDGE_INPUTS: list[tuple[str, str]] = [
    ("empty", ""),
    ("whitespace", "   "),
    ("xss", "<script>alert(1)</script>"),
    ("sql", "' OR '1'='1' --"),
    ("overflow", "A" * 600),
    ("special", "!@#$%^&*()_+-=[]{}|;:'\",.<>/?`~"),
    # exotic chars via escapes (fire emoji, CJK, circled letters, RTL override)
    ("unicode", "\U0001F525 日本語 ⓉⒺⓢⓣ ‮rtl"),
    ("negative", "-99999999"),
]


def adversarial_value(index: int) -> tuple[str, str]:
    """The (name, payload) edge input for the index-th field encountered, cycling.

    Lets a stateless explorer push a DIFFERENT breaking value into each field it
    meets, so one exploration pass covers empty/injection/overflow/unicode rather
    than typing one benign string into all of them.
    """
    return EDGE_INPUTS[index % len(EDGE_INPUTS)]


# The attack catalog: per surface-feature, the moves that try to BREAK it rather
# than confirm it works. Surface-agnostic — the brain consults it when planning and
# when choosing the next action. Distilled from the ui-test adversarial patterns.
PATTERNS: dict[str, list[str]] = {
    "forms": [
        "submit empty (required fields must block + show a validation error, not crash)",
        "submit whitespace-only and wrong-format values",
        "inject <script>/SQL payloads — must be escaped, never executed or 500",
        "paste 500+ chars into every field (overflow / silent truncation)",
        "double-click submit rapidly (debounce — no duplicate request/record)",
        "special chars + unicode/RTL/null in every field",
    ],
    "modals": [
        "open then close via the X, the backdrop, and the Escape key",
        "focus trap — Tab must cycle inside, never reach the page behind",
        "Cancel vs Confirm do DIFFERENT things (cancel must not commit)",
        "reopen after close — stale state must not persist",
    ],
    "navigation": [
        "every link/route reaches a real view (no dead/404 link)",
        "active nav state matches the current route",
        "keyboard-only: Tab to each link, Enter activates",
        "visit a bogus route (/does-not-exist) — graceful 404, not blank/crash",
        "back/forward after navigating keeps state coherent",
    ],
    "empty_states": [
        "a list/table with NO data renders an empty state, not a crash or blank",
        "clearing all items returns to the empty state cleanly",
    ],
    "accessibility": [
        "axe-core: zero serious/critical WCAG violations (audit_dom)",
        "every input has an associated label (audit_dom)",
        "full keyboard-only operation: Tab / Enter / Escape, visible focus ring",
    ],
    "robustness": [
        "no console errors / uncaught exceptions during any flow",
        "no broken images (naturalWidth=0) or failed requests (audit_dom)",
        "an action that should change the screen actually changes it",
    ],
    "responsive": [
        "narrow viewport (~375px): no horizontal overflow or clipped controls",
        "content reflows; nothing overlaps or becomes unclickable",
    ],
}


def catalog_text() -> str:
    """Render the attack catalog for a prompt (the brain's adversarial checklist)."""
    out: list[str] = []
    for feature, moves in PATTERNS.items():
        out.append(f"- {feature.replace('_', ' ').upper()}:")
        out.extend(f"    • {m}" for m in moves)
    return "\n".join(out)
