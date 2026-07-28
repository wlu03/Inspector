from __future__ import annotations

import threading
import time

from . import detection
from .adapters import get_adapter
from .adapters.base import InputAction, SurfaceAdapter
from .assertions import Assertion
from .config import Config
from .findings import build_repro_spec
from .launch.detect import detect_project
from .loop import LoopGuard
from .models import Action, ActionType, Element, SessionRecord, SessionState, Surface
from .perception.detector import OmniParserDetector
from .paths import safe_repo_path
from .perception.som import render_set_of_mark
from .trace import TraceRecorder


SCROLL_DIRECTIONS = ("up", "down")


def _scroll_direction(direction: str | None) -> str:
    """Normalize a scroll direction, refusing anything no surface can actually do.

    Every adapter reads this field as "down unless it says up", so an unrecognized
    value (a typo, "downward", a left/right the surfaces don't implement) would scroll
    DOWN and report success — the agent then concludes the content it asked to scroll
    to isn't there. Better to fail the call with the valid set in the message.
    """
    d = (direction or "down").strip().lower()
    if d not in SCROLL_DIRECTIONS:
        raise ValueError(f"unknown scroll direction {direction!r}; use one of "
                         f"{', '.join(SCROLL_DIRECTIONS)}")
    return d


def _scroll_amount(amount: int | None) -> int:
    """Clamp the scroll distance to at least one notch — a 0 would be a silent no-op."""
    try:
        return max(1, int(amount))
    except (TypeError, ValueError):
        return 1


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
        # The assertion set `check_assertions` last evaluated here — the CORRECT behavior
        # the agent was checking for. Findings filed afterwards (log tap, DOM audit, an
        # oracle-less report_issue) inherit it as their ReproSpec oracle via
        # build_repro_spec, so re-verification has a real check instead of nothing.
        self.last_assertions: list[Assertion] = []
        self._seen_findings: set[str] = set()  # de-dup signatures
        self.created_at = time.monotonic()
        self.touched_at = self.created_at  # last activity, for the reaper
        self._verified_count = 0  # findings total at last verify(), to scope the signal
        self.images_returned = 0  # full SoM PNGs returned at the MCP boundary (cost cap)
        self._launch_error: str | None = None  # set by an async (background) launch
        # Serialize all adapter access: the heartbeat thread and the action loop must
        # never touch the (non-reentrant) transport — e.g. one CDP websocket — at once.
        self._capture_lock = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

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
        if ready:
            self._start_heartbeat()
        return ready

    def teardown(self) -> None:
        self._stop_heartbeat()
        self._safe_teardown()
        self.record.state = SessionState.TORN_DOWN
        self.trace.save_session(self.record)

    # --- heartbeat: snapshot a frame on a timer so idle stretches still show up ---
    def _start_heartbeat(self) -> None:
        interval = self.config.heartbeat_screenshot_s
        if not interval or interval <= 0 or self._heartbeat_thread is not None:
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, args=(interval,), daemon=True, name="inspector-heartbeat"
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        t = self._heartbeat_thread
        if t is not None:
            t.join(timeout=2.0)
            self._heartbeat_thread = None

    def _heartbeat_loop(self, interval: float) -> None:
        # Event.wait doubles as the sleep + a prompt stop signal on teardown.
        while not self._heartbeat_stop.wait(interval):
            # Non-blocking: if an action holds the transport, just skip this tick.
            if not self._capture_lock.acquire(blocking=False):
                continue
            try:
                png = self.adapter.screenshot()
                self.trace.save_frame(png)
            except Exception:
                pass  # a transient screenshot failure shouldn't kill the heartbeat
            finally:
                self._capture_lock.release()

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
        with self._capture_lock:
            png = self.adapter.screenshot()
            elements = self.adapter.detect_elements(png)  # native a11y tree, if any
            if elements is None:
                elements = self.detector.detect(png)       # else OmniParser vision
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
        *,
        to_id: int | None = None,
        to_coords: list[int] | None = None,
        direction: str = "down",
        amount: int = 3,
    ) -> tuple[bytes, bool, list[str]]:
        """Perform one action and return (post-action SoM png, changed, new logs).

        `to_id` / `to_coords` are the DESTINATION of a drag (an element id from the last
        observation, or raw screen px) — a drag without one is a click. `direction` and
        `amount` aim a scroll; they are ignored by the other action types.
        """
        self.touch()
        self.guard.tick()
        self._keepalive()
        self.action_log.append(self._describe_action(
            action_type, target_id, text, key, coords=coords, to_id=to_id,
            to_coords=to_coords, direction=direction,
        ))
        # Hold the capture lock across the whole adapter sequence so a heartbeat
        # snapshot can't interleave on the (non-reentrant) transport mid-action.
        with self._capture_lock:
            before = self.adapter.screenshot()
            frame_before = self.trace.save_frame(before)

            # Resolve the concrete click point now so the trace (and the replay cursor)
            # records WHERE we acted — even for target_id clicks that carry no raw coords.
            click_xy = coords
            drop_xy = to_coords
            try:
                input_action = self._resolve(
                    action_type, target_id, text, key, coords,
                    to_id=to_id, to_coords=to_coords, direction=direction, amount=amount,
                )
                if input_action.x is not None and input_action.y is not None:
                    click_xy = [input_action.x, input_action.y]
                if input_action.to_x is not None and input_action.to_y is not None:
                    drop_xy = [input_action.to_x, input_action.to_y]
                self.adapter.input(input_action)
                time.sleep(0.4)  # settle
                after = self.adapter.screenshot()
            except Exception as exc:
                # record the failed step so the trace/re-run script stays complete
                action = Action(
                    seq=self.action_seq, type=action_type, target_id=target_id,
                    coords=click_xy, to_coords=drop_xy, direction=direction, amount=amount,
                    text=text, key=key, result="error", changed=False,
                    screenshot_before=frame_before, logs=[f"[inspector] action error: {exc}"],
                )
                self.trace.record_action(action)
                self.action_seq += 1
                raise

            frame_after = self.trace.save_frame(after)
            changed = before != after
            logs = self.adapter.logs()
            self.trace.record_logs(logs)
            new_findings = self._ingest_findings(logs)
            # a fresh error/finding counts as progress even if the screen looks the same —
            # a buggy toggle that doesn't repaint is a bug, not a reason to give up.
            self.guard.observe_state(after, signal=new_findings > 0)

            action = Action(
                seq=self.action_seq, type=action_type, target_id=target_id, coords=click_xy,
                to_coords=drop_xy, direction=direction, amount=amount,
                text=text, key=key, result="ok" if changed else "no_change", changed=changed,
                screenshot_before=frame_before, screenshot_after=frame_after, logs=logs,
            )
            self.trace.record_action(action)
            self.action_seq += 1

            elements = self.adapter.detect_elements(after)  # native a11y tree, if any
            if elements is None:
                elements = self.detector.detect(after)       # else OmniParser vision
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
            with self._capture_lock:
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
            finding.repro_spec = build_repro_spec(self)
            self.trace.save_finding(finding)
            self.record.findings.append(finding.id)
            new_ids.append(finding.id)
        return audit, new_ids

    def observation_context(self, labels=frozenset()) -> dict:
        """The channels assertions / oracles evaluate against: visible text, elements,
        the current URL (CDP surfaces), and control-state for the requested labels."""
        _som, elements, _logs = self.observe()
        texts = [e.label for e in elements if e.label]
        try:
            texts += [t.label for t in self.adapter.text_elements() if t.label]
        except Exception:
            pass
        el = [{"label": e.label, "role": e.role} for e in elements]
        url = None
        cdp = getattr(self.adapter, "cdp", None)
        if cdp is not None:
            try:
                v = cdp.evaluate("window.location.href")
                url = v.strip('"') if isinstance(v, str) else v
            except Exception:
                url = None
        want = {str(label).lower() for label in labels}
        states: dict = {}
        for e in elements:
            lab = (e.label or "").lower()
            if lab in want and lab not in states:
                try:
                    states[lab] = self.adapter.control_state(e.id)
                except Exception:
                    pass
        return {"texts": texts, "elements": el, "url": url, "states": states}

    # --- helpers ---
    def _resolve(
        self, action_type: ActionType, target_id: int | None,
        text: str | None, key: str | None, coords: list[int] | None,
        *, to_id: int | None = None, to_coords: list[int] | None = None,
        direction: str = "down", amount: int = 3,
    ) -> InputAction:
        """Turn the tool-level arguments into the one normalized event adapters consume.

        Both endpoints go through the same resolution — an element id from the last
        observation, or raw screen px — because a drag is just a click with a second
        point, and the destination has to be grounded in the SAME coordinate space as
        the origin or the gesture ends somewhere nobody asked for.
        """
        x, y = self._point(target_id, coords)
        to_x, to_y = self._point(to_id, to_coords)
        if action_type == ActionType.DRAG and (to_x is None or to_y is None):
            raise ValueError("drag needs a destination: pass to_id or to_coords")
        return InputAction(
            action_type, x=x, y=y, to_x=to_x, to_y=to_y, text=text, key=key,
            direction=_scroll_direction(direction), amount=_scroll_amount(amount),
        )

    def _point(
        self, target_id: int | None, coords: list[int] | None
    ) -> tuple[int | None, int | None]:
        """One endpoint in screen px: explicit coords win, else the element's center."""
        if coords:
            return int(coords[0]), int(coords[1])
        if target_id is None:
            return None, None
        el = next((e for e in self.last_elements if e.id == target_id), None)
        if el is None:
            raise ValueError(f"unknown target_id {target_id}; call observe first")
        w, h = self.adapter.screen_size()
        return el.center_px(w, h)

    @staticmethod
    def _label_of(elements: list[Element], target_id: int | None) -> str:
        el = next((e for e in elements if e.id == target_id), None)
        return (el.label.strip() if el and el.label else "")

    def _describe_action(
        self, action_type: ActionType, target_id: int | None,
        text: str | None, key: str | None, *, coords: list[int] | None = None,
        to_id: int | None = None, to_coords: list[int] | None = None,
        direction: str = "down",
    ) -> str:
        """One human-readable line for the action log — which is also the repro script.

        `build_repro_spec` parses these lines straight back into ReproSteps, so the
        rendering is a wire format, not decoration: anything this line drops (a drag's
        destination, a scroll's direction) is gone from every finding's repro spec.
        """
        if action_type == ActionType.TYPE:
            return f"type {text!r}"
        if action_type == ActionType.KEY:
            return f"press {key!r}"
        if action_type == ActionType.SCROLL:
            return f"scroll {_scroll_direction(direction)}"
        verb = action_type.value.replace("_", " ")
        if action_type == ActionType.DRAG:
            return (f"{verb} {self._describe_target(target_id, coords)} "
                    f"to {self._describe_target(to_id, to_coords)}")
        if target_id is not None:
            label = self._label_of(self.last_elements, target_id)
            return f"{verb} element #{target_id}" + (f" ({label})" if label else "")
        return verb

    def _describe_target(self, target_id: int | None, coords: list[int] | None) -> str:
        """An endpoint as the log renders it: `element #3 (Save)`, or a raw point."""
        if target_id is not None:
            label = self._label_of(self.last_elements, target_id)
            return f"element #{target_id}" + (f" ({label})" if label else "")
        if coords:
            return f"({coords[0]}, {coords[1]})"
        return "(unknown)"

    def _ingest_findings(self, logs: list[str]) -> int:
        """Save new deterministic findings; return how many were new (for the guard)."""
        new = 0
        for finding in detection.scan_logs(logs, self.record.id, self.record.trace_id):
            sig = detection.finding_signature(finding)
            if sig in self._seen_findings:
                continue  # de-dup repeats across observe/act calls
            self._seen_findings.add(sig)
            if not finding.repro:
                finding.repro = self.action_log[-4:] or ["(observed without prior actions)"]
            finding.repro_spec = build_repro_spec(self)
            self.trace.save_finding(finding)
            self.record.findings.append(finding.id)
            new += 1
        return new


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

    def create(
        self, repo_path: str, surface: Surface | None = None, goal: str = "",
        alias: str | None = None,
    ) -> Session:
        repo_path = safe_repo_path(repo_path, self.config.workspace_roots)
        if surface is None:
            surface = detect_project(repo_path).surface
        session = Session(repo_path, surface, self.config, goal)
        session.record.alias = alias or None
        with self._lock:
            self.sessions[session.record.id] = session
        self._ensure_reaper()
        return session

    def get(self, session_id: str) -> Session:
        """Resolve a live session by its id OR its human alias."""
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None:  # fall back to alias lookup
                session = next(
                    (s for s in self.sessions.values() if s.record.alias == session_id),
                    None,
                )
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
