from __future__ import annotations

import secrets
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Surface(str, Enum):
    WEB = "web"
    ELECTRON = "electron"
    ANDROID = "android"
    IOS = "ios"
    MACOS = "macos"  # native AppKit/SwiftUI Mac apps (AX tree + CGEvent, local only)


class SessionState(str, Enum):
    CREATED = "created"
    PROVISIONING = "provisioning"
    INSTALLING = "installing"
    LAUNCHING = "launching"
    WAITING_READY = "waiting_ready"
    READY = "ready"
    INTERACTING = "interacting"
    DETECTING = "detecting"
    REPORTING = "reporting"
    IDLE = "idle"
    TORN_DOWN = "torn_down"
    ERROR = "error"


class ActionType(str, Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    TYPE = "type"
    SCROLL = "scroll"
    DRAG = "drag"
    KEY = "key"
    WAIT = "wait"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Element(BaseModel):
    """One detected UI element. `id` is the Set-of-Mark number the host picks."""

    id: int
    label: str = ""
    role: str = ""  # "text" | "icon" | ...
    bbox: list[float]  # [x1, y1, x2, y2] as ratios in 0..1
    interactivity: bool = False
    source: str = ""

    def center_px(self, width: int, height: int) -> tuple[int, int]:
        bbox = (list(self.bbox) + [0, 0, 0, 0])[:4]  # tolerate a malformed bbox
        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        # The detector normalizes bboxes to ratios (0..1); guard kept for safety.
        if max(bbox) <= 1.5:
            return int(cx * width), int(cy * height)
        return int(cx), int(cy)


class Action(BaseModel):
    """One step in the loop. The action log is also the deterministic re-run script."""

    seq: int
    type: ActionType
    target_id: int | None = None
    coords: list[int] | None = None
    text: str | None = None
    key: str | None = None
    ts: str = Field(default_factory=_now)
    result: str = "ok"  # ok | no_change | error
    changed: bool = False
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    logs: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fnd"))
    session_id: str = ""
    summary: str = ""
    severity: Severity = Severity.MEDIUM
    confidence: Confidence = Confidence.HIGH
    repro: list[str] = Field(default_factory=list)
    expected: str = ""
    actual: str = ""
    logs: list[str] = Field(default_factory=list)
    suspected_area: str = ""
    screenshot_refs: list[str] = Field(default_factory=list)
    # Where on screenshot_refs[0] the bug is, as [x1,y1,x2,y2] ratios (0..1) — drives
    # the clickable marker in the replay. Empty when the bug has no on-screen location.
    bbox: list[float] = Field(default_factory=list)
    trace_id: str = ""
    status: str = "open"  # open | fixed | verified | dismissed
    pr_url: str | None = None
    ts: str = Field(default_factory=_now)


class Run(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    session_id: str = ""
    trigger: str = "host_request"
    passed: bool = False
    findings: list[str] = Field(default_factory=list)
    iterations: int = 0
    cost_tokens: int = 0
    duration_ms: int = 0
    pr_url: str | None = None
    created_at: str = Field(default_factory=_now)


class SessionRecord(BaseModel):
    """Serializable session metadata (the live `Session` object lives in session.py)."""

    id: str = Field(default_factory=lambda: new_id("ses"))
    repo_path: str
    surface: Surface
    dev_command: str | None = None
    goal: str = ""
    alias: str | None = None  # optional human name (e.g. "checkout-flow") for links/dashboard
    state: SessionState = SessionState.CREATED
    task_id: str | None = None
    trace_id: str = Field(default_factory=lambda: new_id("trc"))
    findings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    ended_at: str | None = None
