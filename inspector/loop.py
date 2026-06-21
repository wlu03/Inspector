from __future__ import annotations

import hashlib
import time


class LoopGuard:
    """Guardrails that keep the autonomous loop from thrashing.

    - hard caps: iterations + wall-clock
    - no-progress detection: hash (screenshot + logs); repeated identical state
      means the loop is stuck and should escalate rather than keep looping.
    """

    def __init__(
        self,
        max_iterations: int = 30,
        max_wall_clock_s: int = 1800,
        no_progress_limit: int = 3,
    ):
        self.max_iterations = max_iterations
        self.max_wall_clock_s = max_wall_clock_s
        self.no_progress_limit = no_progress_limit
        self.iterations = 0
        self.start = time.time()
        self._last_hash: str | None = None
        self._repeat = 0

    def tick(self) -> None:
        self.iterations += 1

    def observe_state(self, screenshot: bytes, signal: bool = False) -> None:
        # Hash the SCREENSHOT only (folding in logs defeats no-progress on apps with
        # heartbeat logs). `signal` = a fresh finding this step → counts as progress even
        # if the screen is unchanged, so finding a bug doesn't trip the no-progress exit.
        digest = hashlib.sha256(screenshot).hexdigest()
        if signal or digest != self._last_hash:
            self._repeat = 0
        else:
            self._repeat += 1
        self._last_hash = digest

    def exhausted(self) -> str | None:
        """Return a stop reason if a guardrail tripped, else None."""
        if self.iterations >= self.max_iterations:
            return "max_iterations"
        if time.time() - self.start >= self.max_wall_clock_s:
            return "max_wall_clock"
        if self._repeat >= self.no_progress_limit:
            return "no_progress"
        return None
