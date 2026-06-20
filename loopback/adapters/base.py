from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import ActionType, Surface


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

    @abstractmethod
    def screen_size(self) -> tuple[int, int]:
        """Return (width, height) in pixels — used to map bbox ratios to clicks."""

    @abstractmethod
    def teardown(self) -> None:
        """Stop the app and release the runtime."""
