from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import ActionType, Element, Surface


@dataclass
class InputAction:
    """A normalized input event, dispatched by an adapter to its surface backend."""

    type: ActionType
    x: int | None = None
    y: int | None = None
    to_x: int | None = None
    to_y: int | None = None
    text: str | None = None
    key: str | None = None
    direction: str = "down"
    amount: int = 3


class SurfaceAdapter(ABC):
    """The single interface every surface implements.

    The entire core (MCP tools, session manager, perception, action dispatcher,
    detection, trace, loop) is written once against this interface and never
    branches on surface type. Adding a surface = implementing one of these.
    """

    surface: Surface

    @abstractmethod
    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        """Boot the app in its runtime (does not block on readiness)."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Block until the app is interactive; return False on timeout."""

    @abstractmethod
    def screenshot(self) -> bytes:
        """Return a PNG of the current screen."""

    @abstractmethod
    def input(self, action: InputAction) -> None:
        """Inject one input event."""

    @abstractmethod
    def logs(self) -> list[str]:
        """Return new log lines since the previous call (crash/error signal)."""

    def rendered_elements(self) -> list[str]:
        """Labels/text of the interactive elements ACTUALLY rendered right now.

        The per-surface hook for the code-aware "missing element" oracle: the core
        diffs these against what the source code declares, so it can surface an
        element that was supposed to appear but didn't. Web/Electron read the live
        DOM (CDP); Android/iOS read the accessibility tree. Not abstract — a surface
        that can't enumerate yet inherits this empty default (oracle just no-ops).
        """
        return []

    def audit_dom(self) -> dict:
        """Deterministic DOM audit: axe-core violations, broken images, unlabeled inputs.

        The per-surface hook for the strongest evidence tier (structured facts, not
        vision judgments). Web/Electron run it over CDP; surfaces without a DOM
        inherit this empty default (the audit just no-ops).
        """
        return {}

    def detect_elements(self, screenshot: bytes) -> list[Element] | None:
        """Optional native element source (the accessibility tree).

        Return the elements directly — the SAME `Element[]` (bbox as 0..1 ratios,
        Set-of-Mark id = list position) the OmniParser detector produces — or `None`
        to fall back to the vision detector. Native surfaces (iOS/macOS) override this
        with the a11y tree; web/Electron/Android keep `None` and ground via OmniParser.
        Clicks still go through pixels (`Element.center_px`), so this is purely an
        additive grounding source — the pure-computer-use action path is unchanged.
        """
        return None

    def control_state(self, element_id: int) -> dict:
        """Structured control state for the element with this Set-of-Mark id —
        {role, value, checked, pressed, ariaChecked, selected, expanded, text}.

        The spine of the Cartographer STATE_SYNC oracle (docs/15): it compares a
        control to ITSELF across one action, so a label that flips while the backing
        state doesn't (or vice-versa) is caught without ever judging injected input.
        Default `{}` (no structured state available); CDP/AX adapters override.
        """
        return {}

    def text_elements(self) -> list[Element]:
        """Non-interactive displayed text (values/captions the interactive grounding
        misses — a counter's display, a status caption). Cartographer oracles READ
        these to measure state. Default `[]`; CDP/AX adapters override. Ids should not
        collide with `detect_elements`' ids (the caller offsets them)."""
        return []

    @abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Return (width, height) in pixels — used to map bbox ratios to clicks."""

    @abstractmethod
    def teardown(self) -> None:
        """Stop the app and release the runtime."""
