from __future__ import annotations

import time

from ..config import Config
from ..models import ActionType
from ..sandbox import E2BSandbox
from .base import InputAction, SurfaceAdapter


class DesktopAdapter(SurfaceAdapter):
    """Shared E2B-desktop behavior for the Linux plane (web + Electron).

    Subclasses implement `launch` and `is_ready`; everything else is the same
    sandbox-backed screenshot/input/logs path.
    """

    def __init__(self, config: Config):
        self.config = config
        self.sandbox = E2BSandbox(config)
        self.project = None

    def screenshot(self) -> bytes:
        return self.sandbox.screenshot()

    def logs(self) -> list[str]:
        return self.sandbox.drain_logs()

    def screen_size(self) -> tuple[int, int]:
        return self.sandbox.screen_size()

    def teardown(self) -> None:
        self.sandbox.kill()

    def input(self, action: InputAction) -> None:
        t = action.type
        if t == ActionType.CLICK:
            self.sandbox.left_click(action.x, action.y)
        elif t == ActionType.DOUBLE_CLICK:
            self.sandbox.double_click(action.x, action.y)
        elif t == ActionType.TYPE:
            # focus the target field first — typing without focus drops the keystrokes,
            # so form inputs never fill and form-dependent bugs never trigger.
            if action.x is not None and action.y is not None:
                self.sandbox.left_click(action.x, action.y)
                time.sleep(0.15)
            self.sandbox.write(action.text or "")
        elif t == ActionType.KEY:
            self.sandbox.press(action.key or "")
        elif t == ActionType.SCROLL:
            self.sandbox.scroll(action.direction, action.amount)
        elif t == ActionType.DRAG:
            self.sandbox.drag((action.x, action.y), (action.to_x, action.to_y))
        elif t == ActionType.WAIT:
            pass
