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

    def network(self) -> list[dict]:
        """HTTP requests the app made since the previous call — the API-facing channel.

        Most bugs in an app someone just built are backend bugs: a 500, a 404 on a
        mistyped route, a CORS rejection, a fetch that hangs. None of those print a
        console line or change a pixel, so `logs()` and the screenshot both report a
        clean run. Records are {request_id, method, url, resource_type, status,
        mime_type, failed, error, duration_ms}.

        Kept separate from `logs()` on purpose — a surface must not fold network events
        into its console tap, or the same failure is counted on both channels. Surfaces
        that can't observe traffic inherit this empty default, exactly like `audit_dom`
        and `text_elements`.
        """
        return []

    def navigate(self, url: str) -> bool:
        """Send the app to `url`; True only if the surface actually went there.

        Whole classes of bug live behind a route change — a dead link, a blank
        /does-not-exist instead of a 404 view, state that survives a route it should
        not. None of that is reachable while the only way in is the screen the app
        happened to boot on.

        The default is False, NOT a silent no-op, and that distinction is the contract:
        a surface that cannot navigate (a phone screen with no address bar) must say so,
        because a no-op that returns success reads to the caller as "the bogus route
        rendered fine" about a page that never left home.
        """
        return False

    def go_back(self) -> bool:
        """Step back one entry in session history; False if the surface can't, or
        if there is no entry to go back to (running off the end of the history is a
        legitimate answer, not an error)."""
        return False

    def go_forward(self) -> bool:
        """Step forward one entry in session history; False if unsupported or already
        at the newest entry. Together with `go_back` this is what makes "back/forward
        after navigating keeps state coherent" an executable check."""
        return False

    def reload(self) -> bool:
        """Reload the current view; False if the surface can't. Reload is how state
        that only LOOKS persisted gets caught — the optimistic update that was never
        written, the form that silently lost its draft."""
        return False

    def set_viewport(self, width: int, height: int, mobile: bool = False) -> bool:
        """Resize the app's viewport to width x height CSS px; False if unsupported.

        The responsive checks (a ~375px phone width: no horizontal overflow, nothing
        clipped or unclickable) cannot run on a screen size fixed at launch. A surface
        that overrides this MUST also move whatever coordinate space it maps element
        boxes through, or every click after the resize lands at the old scale.
        """
        return False

    def seed_state(self, state: dict) -> bool:
        """Install a previously captured session before the app is tested.

        Every session otherwise starts logged out, and on any app with auth that means
        clicking through the login UI on every single run — slow, brittle, and it burns a
        30-iteration budget before reaching the feature that was actually built. Seeding
        turns "log in, then test" into "test", and makes a captured session replayable.

        `state` is the plain dict `capture_state` returns — {origin, cookies,
        local_storage, session_storage} — so it round-trips through a file unchanged.

        The default is False, NOT a silent no-op, for the same reason as `navigate`: a
        surface that cannot seed has to SAY so, because a caller told "seeded" will read
        every logged-out screen that follows as a bug in the app rather than as a session
        that was never installed.
        """
        return False

    def capture_state(self) -> dict:
        """Snapshot the current session as a JSON-serialisable dict; `{}` if unsupported.

        The other half of `seed_state`: log in once by hand, capture, keep the dict, and
        every later run starts authenticated. `{}` is the honest empty answer for a
        surface with no session to capture — it is also what a caller should refuse to
        write to a state file, since seeding it back would install nothing.
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
