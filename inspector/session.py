from __future__ import annotations

import time

from . import detection
from .adapters import get_adapter
from .adapters.base import InputAction, SurfaceAdapter
from .config import Config
from .launch.detect import detect_project
from .loop import LoopGuard
from .models import Action, ActionType, Element, SessionRecord, SessionState, Surface
from .perception.detector import OmniParserDetector
from .perception.som import render_set_of_mark
from .trace import TraceRecorder


class Session:
    """A live verification session against one running app on one surface."""

    def __init__(self, repo_path: str, surface: Surface, config: Config, goal: str = ""):
        self.config = config
        self.record = SessionRecord(repo_path=repo_path, surface=surface, goal=goal)
        self.adapter: SurfaceAdapter = get_adapter(surface, config)
        self.detector = OmniParserDetector(config)
        self.trace = TraceRecorder(config.trace_root, self.record.id)
        self.guard = LoopGuard(config.max_iterations, config.max_wall_clock_s)
        self.last_elements: list[Element] = []
        self.action_seq = 0

    # --- lifecycle ---
    def launch(self, dev_command: str | None = None) -> bool:
        self.record.dev_command = dev_command
        self.record.state = SessionState.LAUNCHING
        try:
            self.adapter.launch(self.record.repo_path, dev_command)
            self.record.state = SessionState.WAITING_READY
            ready = self.adapter.is_ready()
        except Exception:
            # never leak the sandbox started inside adapter.launch
            self.record.state = SessionState.ERROR
            self.trace.save_session(self.record)
            self._safe_teardown()
            raise
        self.record.state = SessionState.READY if ready else SessionState.ERROR
        self.trace.save_session(self.record)
        return ready

    def teardown(self) -> None:
        self._safe_teardown()
        self.record.state = SessionState.TORN_DOWN
        self.trace.save_session(self.record)

    def _safe_teardown(self) -> None:
        try:
            self.adapter.teardown()
        except Exception:
            pass

    def _keepalive(self) -> None:
        sandbox = getattr(self.adapter, "sandbox", None)
        if sandbox is not None:
            try:
                sandbox.keep_alive()
            except Exception:
                pass

    # --- the loop ---
    def observe(self) -> tuple[bytes, list[Element], list[str]]:
        self._keepalive()
        self.record.state = SessionState.INTERACTING
        png = self.adapter.screenshot()
        elements = self.detector.detect(png)
        self.last_elements = elements
        som = render_set_of_mark(png, elements)
        self.trace.save_frame(som)
        logs = self.adapter.logs()
        self.trace.record_logs(logs)
        self._ingest_findings(logs)
        return som, elements, logs

    def act(
        self,
        action_type: ActionType,
        target_id: int | None = None,
        text: str | None = None,
        key: str | None = None,
        coords: list[int] | None = None,
    ) -> tuple[bytes, bool, list[str]]:
        self.guard.tick()
        self._keepalive()
        before = self.adapter.screenshot()
        frame_before = self.trace.save_frame(before)

        try:
            self.adapter.input(self._resolve(action_type, target_id, text, key, coords))
            time.sleep(0.4)  # settle
            after = self.adapter.screenshot()
        except Exception as exc:
            # record the failed step so the trace/re-run script stays complete
            action = Action(
                seq=self.action_seq, type=action_type, target_id=target_id,
                coords=coords, text=text, key=key, result="error", changed=False,
                screenshot_before=frame_before, logs=[f"[inspector] action error: {exc}"],
            )
            self.trace.record_action(action)
            self.action_seq += 1
            raise

        frame_after = self.trace.save_frame(after)
        changed = before != after
        logs = self.adapter.logs()
        self.guard.observe_state(after, logs)
        self.trace.record_logs(logs)
        self._ingest_findings(logs)

        action = Action(
            seq=self.action_seq, type=action_type, target_id=target_id, coords=coords,
            text=text, key=key, result="ok" if changed else "no_change", changed=changed,
            screenshot_before=frame_before, screenshot_after=frame_after, logs=logs,
        )
        self.trace.record_action(action)
        self.action_seq += 1

        elements = self.detector.detect(after)
        self.last_elements = elements
        som = render_set_of_mark(after, elements)
        return som, changed, logs

    # --- helpers ---
    def _resolve(
        self, action_type: ActionType, target_id: int | None,
        text: str | None, key: str | None, coords: list[int] | None,
    ) -> InputAction:
        if action_type == ActionType.DRAG:
            # DRAG needs a destination, which the act tool can't yet express.
            raise NotImplementedError(
                "DRAG is not supported yet (no destination parameter) — see review follow-ups"
            )
        if coords:
            return InputAction(action_type, x=coords[0], y=coords[1], text=text, key=key)
        if target_id is not None:
            el = next((e for e in self.last_elements if e.id == target_id), None)
            if el is None:
                raise ValueError(f"unknown target_id {target_id}; call observe first")
            w, h = self.adapter.screen_size()
            cx, cy = el.center_px(w, h)
            return InputAction(action_type, x=cx, y=cy, text=text, key=key)
        return InputAction(action_type, text=text, key=key)

    def _ingest_findings(self, logs: list[str]) -> None:
        for finding in detection.scan_logs(logs, self.record.id, self.record.trace_id):
            self.trace.save_finding(finding)
            self.record.findings.append(finding.id)


class SessionManager:
    """Owns all live sessions for the server process."""

    def __init__(self, config: Config):
        self.config = config
        self.sessions: dict[str, Session] = {}

    def create(self, repo_path: str, surface: Surface | None = None, goal: str = "") -> Session:
        if surface is None:
            surface = detect_project(repo_path).surface
        session = Session(repo_path, surface, self.config, goal)
        self.sessions[session.record.id] = session
        return session

    def get(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            raise KeyError(f"no session {session_id!r}")
        return self.sessions[session_id]

    def stop(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        # tear down first (release the billed sandbox); only then drop the handle,
        # so a flaky teardown can be retried instead of orphaning the sandbox.
        try:
            session.teardown()
        finally:
            self.sessions.pop(session_id, None)
