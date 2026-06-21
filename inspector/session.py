from __future__ import annotations

import threading
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
        self.adapter: SurfaceAdapter = get_adapter(surface, config, repo_path=repo_path)
        self.detector = OmniParserDetector(config)
        self.trace = TraceRecorder(config.trace_root, self.record.id)
        self.guard = LoopGuard(config.max_iterations, config.max_wall_clock_s)
        self.last_elements: list[Element] = []
        self.action_seq = 0
        self.plan = None  # TestPlan, set via the set_plan tool
        self.action_log: list[str] = []  # human-readable steps, used for repro
        self._seen_findings: set[str] = set()  # de-dup signatures
        self.created_at = time.monotonic()
        self.touched_at = self.created_at  # last activity, for the reaper
        self._verified_count = 0  # findings total at last verify(), to scope the signal
        self.images_returned = 0  # full SoM PNGs returned at the MCP boundary (cost cap)
        self._launch_error: str | None = None  # set by an async (background) launch

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

    def touch(self) -> None:
        """Record recent activity so the reaper won't collect a live session."""
        self.touched_at = time.monotonic()

    def image_allowed(self) -> bool:
        """Whether to return a full SoM image now, honoring the per-session cap."""
        cap = self.config.max_images_per_session
        if cap and self.images_returned >= cap:
            return False
        self.images_returned += 1
        return True

    # --- the loop ---
    def observe(self) -> tuple[bytes, list[Element], list[str]]:
        self.touch()
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
        self.touch()
        self.guard.tick()
        self._keepalive()
        self.action_log.append(self._describe_action(action_type, target_id, text, key))
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

    def audit(self) -> tuple[dict, list[str]]:
        """Run the deterministic DOM audit and ingest any issues as Findings.

        The strongest evidence tier: structured facts from the live DOM (axe-core
        WCAG violations, broken images, unlabeled inputs), de-duped against findings
        already seen this session. Returns (raw audit dict, ids of new findings).
        No-ops to ({}, []) on surfaces without a DOM.
        """
        from .audit import audit_to_findings

        self.touch()
        try:
            audit = self.adapter.audit_dom()
        except Exception:
            audit = {}
        new_ids: list[str] = []
        for finding in audit_to_findings(
            audit, session_id=self.record.id, trace_id=self.record.trace_id
        ):
            sig = detection.finding_signature(finding)
            if sig in self._seen_findings:
                continue  # de-dup against the log tap + earlier audits
            self._seen_findings.add(sig)
            if not finding.repro:
                finding.repro = self.action_log[-4:] or ["deterministic DOM audit"]
            self.trace.save_finding(finding)
            self.record.findings.append(finding.id)
            new_ids.append(finding.id)
        return audit, new_ids

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

    @staticmethod
    def _label_of(elements: list[Element], target_id: int | None) -> str:
        el = next((e for e in elements if e.id == target_id), None)
        return (el.label.strip() if el and el.label else "")

    def _describe_action(
        self, action_type: ActionType, target_id: int | None,
        text: str | None, key: str | None,
    ) -> str:
        if action_type == ActionType.TYPE:
            return f"type {text!r}"
        if action_type == ActionType.KEY:
            return f"press {key!r}"
        verb = action_type.value.replace("_", " ")
        if target_id is not None:
            label = self._label_of(self.last_elements, target_id)
            return f"{verb} element #{target_id}" + (f" ({label})" if label else "")
        return verb

    def _ingest_findings(self, logs: list[str]) -> None:
        for finding in detection.scan_logs(logs, self.record.id, self.record.trace_id):
            sig = detection.finding_signature(finding)
            if sig in self._seen_findings:
                continue  # de-dup repeats across observe/act calls
            self._seen_findings.add(sig)
            if not finding.repro:
                finding.repro = self.action_log[-4:] or ["(observed without prior actions)"]
            self.trace.save_finding(finding)
            self.record.findings.append(finding.id)


class SessionManager:
    """Owns all live sessions for the server process.

    Thread-safe (FastMCP serves tools from a threadpool) and runs a daemon reaper
    that tears down sessions idle past `session_idle_ttl_s` or older than
    `sandbox_timeout_s` — so a host that crashes or forgets `stop()` can't leak a
    billed sandbox.
    """

    def __init__(self, config: Config):
        self.config = config
        self.sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._reaper: threading.Thread | None = None

    def create(self, repo_path: str, surface: Surface | None = None, goal: str = "") -> Session:
        if surface is None:
            surface = detect_project(repo_path).surface
        session = Session(repo_path, surface, self.config, goal)
        with self._lock:
            self.sessions[session.record.id] = session
        self._ensure_reaper()
        return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(f"no session {session_id!r}")
        session.touch()  # a tool call is activity — keep it off the reaper's list
        return session

    def stop(self, session_id: str) -> None:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            return
        # tear down OUTSIDE the lock (it can block on the network) — release the
        # billed sandbox first, then drop the handle so a flaky teardown can retry.
        try:
            session.teardown()
        finally:
            with self._lock:
                self.sessions.pop(session_id, None)

    # --- reaper ---
    def reap(self, now: float) -> list[str]:
        """Stop sessions idle past the TTL, or older than the sandbox lifetime.

        Takes `now` (a monotonic timestamp) so it's unit-testable without the
        background thread. Returns the ids it tore down.
        """
        ttl = self.config.session_idle_ttl_s
        max_age = self.config.sandbox_timeout_s
        stale: list[str] = []
        with self._lock:
            for sid, s in list(self.sessions.items()):
                idle = now - s.touched_at
                age = now - s.created_at
                if (ttl > 0 and idle > ttl) or (max_age > 0 and age > max_age):
                    stale.append(sid)
        for sid in stale:
            self.stop(sid)  # acquires the lock itself
        return stale

    def _ensure_reaper(self) -> None:
        if self._reaper is not None or self.config.session_idle_ttl_s <= 0:
            return
        t = threading.Thread(target=self._reaper_loop, name="inspector-reaper", daemon=True)
        self._reaper = t
        t.start()

    def _reaper_loop(self) -> None:
        while True:
            time.sleep(max(self.config.reaper_interval_s, 1))
            try:
                self.reap(time.monotonic())
            except Exception:
                pass
