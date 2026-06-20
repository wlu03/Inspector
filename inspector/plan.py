from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .models import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScenarioStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class Scenario(BaseModel):
    """One thing to test — a flow, feature, or edge case."""

    id: str = Field(default_factory=lambda: new_id("scn"))
    title: str
    rationale: str = ""  # why this part matters
    steps: list[str] = Field(default_factory=list)  # planned steps
    expected: str = ""  # the expected outcome to verify
    status: ScenarioStatus = ScenarioStatus.PENDING
    notes: str = ""  # what actually happened
    finding_ids: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    """The overall plan for a session: the scenarios covering the app's parts."""

    id: str = Field(default_factory=lambda: new_id("plan"))
    session_id: str = ""
    goal: str = ""
    scenarios: list[Scenario] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)

    def get(self, scenario_id: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.id == scenario_id), None)

    def pending(self) -> list[Scenario]:
        return [s for s in self.scenarios if s.status == ScenarioStatus.PENDING]


def build_plan(session_id: str, goal: str, scenarios: list[dict]) -> TestPlan:
    out: list[Scenario] = []
    for s in scenarios or []:
        out.append(
            Scenario(
                title=str(s.get("title", "")),
                rationale=str(s.get("rationale", "")),
                steps=[str(x) for x in (s.get("steps") or [])],
                expected=str(s.get("expected", "")),
            )
        )
    return TestPlan(session_id=session_id, goal=goal, scenarios=out)
