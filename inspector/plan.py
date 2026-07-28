"""Test plans: what an agent decided to test, and — because they are saved per repo —
what it can be asked to test AGAIN.

A plan used to live only on the live `Session`, so every run re-invented its own
scenarios and two runs of the same app were never comparable: nothing regressed,
because nothing was the same thing twice. Persisting a plan under the trace root turns
it into a suite the owner can re-run after a change (`run_plan`), and gives each
scenario a history — the one thing that makes "this passed last week and fails today"
sayable at all.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .assertions import Assertion
from .models import new_id
from .paths import plan_file, plans_dir, plans_root, valid_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScenarioStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class ScenarioRun(BaseModel):
    """One execution of one scenario — the row the cross-run history is made of."""

    session_id: str = ""
    status: ScenarioStatus = ScenarioStatus.PENDING
    notes: str = ""  # what actually happened that time
    finding_ids: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=_now)


class Scenario(BaseModel):
    """One thing to test — a flow, feature, or edge case."""

    id: str = Field(default_factory=lambda: new_id("scn"))
    title: str
    rationale: str = ""  # why this part matters
    steps: list[str] = Field(default_factory=list)  # planned steps
    expected: str = ""  # the expected outcome to verify
    # The scenario's ORACLE: the machine-checkable form of `expected`, evaluated after
    # the steps run. Without it a re-run can only report that nothing crashed, which is
    # the difference between a suite and a smoke test.
    assertions: list[Assertion] = Field(default_factory=list)
    status: ScenarioStatus = ScenarioStatus.PENDING  # the most recent run's verdict
    notes: str = ""  # what actually happened
    finding_ids: list[str] = Field(default_factory=list)  # every finding, across runs
    history: list[ScenarioRun] = Field(default_factory=list)  # oldest run first

    def record_run(
        self, status: ScenarioStatus, session_id: str = "", notes: str = "",
        finding_ids: list[str] | None = None,
    ) -> ScenarioRun:
        """Record this run's outcome without discarding the previous ones.

        Re-recording within the SAME session replaces that session's row rather than
        appending a second one, so the history stays one row per RUN — an agent that
        corrects a verdict mid-run is not a regression, and it must not look like one.
        `finding_ids` accumulates across runs (the union) because a finding filed on an
        earlier run is still evidence about this scenario after the run that filed it is
        long gone; the per-run row keeps which run saw what.
        """
        run = ScenarioRun(session_id=session_id, status=ScenarioStatus(status), notes=notes,
                          finding_ids=list(finding_ids or []))
        if session_id and self.history and self.history[-1].session_id == session_id:
            self.history[-1] = run
        else:
            self.history.append(run)
        self.status = run.status
        self.notes = notes
        for fid in run.finding_ids:
            if fid not in self.finding_ids:
                self.finding_ids.append(fid)
        return run

    def regressed(self) -> bool:
        """True when this scenario passed on some earlier run and fails on the latest."""
        return (self.status == ScenarioStatus.FAILED
                and any(r.status == ScenarioStatus.PASSED for r in self.history[:-1]))


class TestPlan(BaseModel):
    """The overall plan for a session: the scenarios covering the app's parts."""

    id: str = Field(default_factory=lambda: new_id("plan"))
    session_id: str = ""  # the session that first wrote it
    repo_path: str = ""  # the app it belongs to; a plan is filed per repo
    goal: str = ""
    scenarios: list[Scenario] = Field(default_factory=list)
    runs: list[str] = Field(default_factory=list)  # session ids that walked it, oldest first
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    def get(self, scenario_id: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.id == scenario_id), None)

    def pending(self) -> list[Scenario]:
        return [s for s in self.scenarios if s.status == ScenarioStatus.PENDING]

    def totals(self) -> dict[str, int]:
        """Scenario counts by current status — the plan's verdict at a glance."""
        out: dict[str, int] = {}
        for s in self.scenarios:
            out[s.status.value] = out.get(s.status.value, 0) + 1
        return out

    def regressions(self) -> list[Scenario]:
        """Scenarios that used to pass and no longer do — the reason to keep a plan."""
        return [s for s in self.scenarios if s.regressed()]

    def begin_run(self, session_id: str) -> None:
        """Open a fresh run: remember the session, and put every scenario back to PENDING.

        The reset is deliberate. A run that dies halfway would otherwise leave the
        scenarios it never reached showing LAST run's verdict, and a stale `passed` is
        the one answer a test suite must never give.
        """
        if session_id and session_id not in self.runs:
            self.runs.append(session_id)
        for s in self.scenarios:
            s.status = ScenarioStatus.PENDING

    def adopt_history(self, prior: "TestPlan") -> None:
        """Carry a saved plan's identity and per-scenario history onto this rewrite.

        `set_plan` is called again whenever the agent adapts the plan mid-run, and it
        rebuilds the scenarios from scratch (new ids). Matching the rewrite up with what
        was already on disk BY TITLE is what keeps a scenario's history attached to it
        across those rewrites — otherwise adapting the plan would silently reset every
        streak the plan existed to record.
        """
        by_title = {_title_key(s.title): s for s in prior.scenarios if _title_key(s.title)}
        for s in self.scenarios:
            old = by_title.get(_title_key(s.title))
            if old is None:
                continue
            s.status = old.status
            s.notes = old.notes
            s.finding_ids = list(old.finding_ids)
            s.history = list(old.history)
        self.created_at = prior.created_at
        self.runs = list(prior.runs)


def _title_key(title: str) -> str:
    """Compact form of a scenario title, so re-wording the caps/spacing still matches."""
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def _assertions(raw) -> list[Assertion]:
    """Parse a scenario's oracle, dropping anything malformed.

    A scenario dict comes straight off a tool call, so one bad assertion must not cost
    the whole plan — the scenario simply runs with a weaker oracle, which is visible in
    the saved plan, rather than the call failing.
    """
    out: list[Assertion] = []
    for a in raw or []:
        try:
            out.append(a if isinstance(a, Assertion) else Assertion.model_validate(a))
        except Exception:
            continue
    return out


def build_plan(
    session_id: str, goal: str, scenarios: list[dict], repo_path: str = "",
    plan_id: str = "",
) -> TestPlan:
    out: list[Scenario] = []
    for s in scenarios or []:
        out.append(
            Scenario(
                title=str(s.get("title", "")),
                rationale=str(s.get("rationale", "")),
                steps=[str(x) for x in (s.get("steps") or [])],
                expected=str(s.get("expected", "")),
                assertions=_assertions(s.get("assertions")),
            )
        )
    plan = TestPlan(session_id=session_id, goal=goal, scenarios=out, repo_path=repo_path)
    if plan_id and valid_id(plan_id):
        plan.id = plan_id
    return plan


# --- the durable store: one JSON file per plan, filed under the repo it tests ---

def save_plan(trace_root: str, plan: TestPlan, workspace_roots: list[str] | None = None) -> str:
    """Write a plan to `<trace_root>/plans/<repo_key>/<plan_id>.json`; returns the path.

    The repo comes off the plan itself, so a plan can only ever be filed under the app it
    was written for, and the path is built by `paths.plan_file` (which canonicalizes the
    repo through `safe_repo_path` and refuses a plan id that is not a single segment).
    """
    path = plan_file(trace_root, plan.repo_path, plan.id, workspace_roots)
    plan.updated_at = _now()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(plan.model_dump_json(indent=2))
    return path


def _read_plan(path: str) -> TestPlan | None:
    """One plan off disk, or None — an unreadable/old-schema file is not a crash."""
    try:
        with open(path) as f:
            return TestPlan.model_validate_json(f.read())
    except Exception:
        return None


def load_plan(
    trace_root: str, repo_path: str, plan_id: str,
    workspace_roots: list[str] | None = None,
) -> TestPlan | None:
    """The saved plan `plan_id` for this repo, or None when there isn't one."""
    if not valid_id(plan_id):
        return None
    return _read_plan(plan_file(trace_root, repo_path, plan_id, workspace_roots))


def list_plans(
    trace_root: str, repo_path: str, workspace_roots: list[str] | None = None,
) -> list[TestPlan]:
    """Every plan saved for this repo, most recently updated first."""
    directory = plans_dir(trace_root, repo_path, workspace_roots)
    plans: list[TestPlan] = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    for name in names:
        if not name.endswith(".json"):
            continue
        plan = _read_plan(os.path.join(directory, name))
        if plan is not None:
            plans.append(plan)
    return sorted(plans, key=lambda p: p.updated_at, reverse=True)


def find_plan(trace_root: str, plan_id: str) -> TestPlan | None:
    """A plan by id alone, across every repo — what `get_plan(plan_id)` is asking for.

    A plan id is the handle the agent is holding after `set_plan`, and it should not have
    to remember which repo path went with it. The id is validated as a single segment
    first, so the scan can only ever look for `<some repo dir>/<plan_id>.json`.
    """
    if not valid_id(plan_id):
        return None
    root = plans_root(trace_root)
    try:
        repos = sorted(os.listdir(root))
    except OSError:
        return None
    for repo in repos:
        path = os.path.join(root, repo, f"{plan_id}.json")
        if os.path.isfile(path):
            plan = _read_plan(path)
            if plan is not None:
                return plan
    return None


# --- re-running a saved plan ---

# How a scenario step is turned back into something the app can be driven with. A plan is
# prose written by an agent, so the parse is deliberately shallow: a verb it recognises,
# and the rest as the thing to act on. Anything else parses to None and the scenario says
# it could not be walked — guessing at "confirm the total updates" would drive the app
# somewhere nobody asked for and then call whatever happened a pass.
_STEP_VERBS: tuple[tuple[str, str], ...] = (
    ("double click", "double_click"), ("double-click", "double_click"),
    ("right click", "right_click"), ("right-click", "right_click"),
    ("go back", "back"), ("go forward", "forward"),
    ("navigate to", "navigate"), ("go to", "navigate"), ("visit", "navigate"),
    ("click on", "click"), ("click", "click"), ("tap on", "click"), ("tap", "click"),
    ("hover over", "hover"), ("hover", "hover"),
    ("type", "type"), ("enter", "type"), ("fill in", "type"), ("fill", "type"),
    ("press", "key"), ("hit", "key"),
    ("scroll", "scroll"), ("reload", "reload"), ("refresh", "reload"), ("wait", "wait"),
)
# Actions that need no argument — a step that is just the verb still replays.
_BARE_ACTIONS = frozenset({"back", "forward", "reload", "scroll", "wait"})
# Nouns an author appends to a label ("the Save button") that are not part of the label.
_TRAILING_NOUNS = ("button", "link", "field", "input", "icon", "tab", "menu", "item",
                   "checkbox", "toggle", "option", "box")
_QUOTED = re.compile(r"['\"‘’“”](.+?)['\"‘’“”]")


def _phrase(rest: str) -> str:
    """The thing a step acts on, stripped of the prose around it.

    Quoted text wins outright — an author who wrote `click "Save"` has already told us
    exactly what the locator is. Otherwise the leading article and the trailing noun go,
    so "the Save button" and "Save" reach the element finder as the same label.
    """
    s = rest.strip().strip(".;:,")
    m = _QUOTED.search(s)
    if m:
        return m.group(1).strip()
    s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+(?:%s)$" % "|".join(_TRAILING_NOUNS), "", s, flags=re.IGNORECASE)
    return s.strip()


def parse_step(step: str):
    """Turn one written scenario step into a replayable `ReproStep`, or None.

    None means "this line is not an instruction" — a check ("the total should update"), a
    comment, a verb no surface has. The caller reports those instead of executing
    something else in their place.
    """
    from .models import ReproStep

    text = (step or "").strip()
    low = text.lower()
    for prefix, action in _STEP_VERBS:
        if not (low == prefix or low.startswith(prefix + " ")):
            continue
        arg = _phrase(text[len(prefix):])
        if action == "navigate":
            return ReproStep(action=action, url=arg) if arg else None
        if action == "type":
            # "type 'admin' into the email field" — the target is the field, but a TYPE
            # goes to whatever holds focus, so only the value is kept.
            value = re.split(r"\s+(?:into|in|on)\s+", arg, maxsplit=1)[0].strip()
            return ReproStep(action=action, text=value) if value else None
        if action == "key":
            return ReproStep(action=action, key=arg) if arg else None
        if action in _BARE_ACTIONS:
            return ReproStep(action=action)
        return ReproStep(action=action, locator=arg) if arg else None
    return None


def _judge_scenario(session, scenario: Scenario) -> tuple[ScenarioStatus, str]:
    """The verdict for a scenario whose steps all replayed, and why.

    Evidence only, in order of strength: the scenario's own oracle if it has one (a real
    check of the thing the scenario is about), otherwise the deterministic findings the
    walk produced. A scenario with no oracle that files nothing comes back PASSED with
    the caveat in its notes, because "nothing broke" is genuinely weaker than "the
    expected thing happened" and the notes are what the owner reads.
    """
    if scenario.assertions:
        from .assertions import evaluate_assertions, summarize

        labels = {a.on for a in scenario.assertions if getattr(a, "on", "")}
        results = evaluate_assertions(scenario.assertions, **session.observation_context(labels))
        overall = summarize(results)["overall"]
        detail = "; ".join(f"{r.kind.value} {r.target}: {r.status.value}" for r in results)[:400]
        if overall == "pass":
            return ScenarioStatus.PASSED, f"oracle passed — {detail}"
        if overall == "fail":
            return ScenarioStatus.FAILED, f"oracle failed — {detail}"
        return ScenarioStatus.BLOCKED, f"oracle inconclusive — {detail}"
    return ScenarioStatus.PASSED, ("steps replayed with no new findings; no oracle on this "
                                   "scenario, so its expected outcome was not checked")


def run_scenario(session, scenario: Scenario) -> ScenarioRun:
    """Walk one saved scenario against the running app and record what happened.

    Nothing here is optimistic. A scenario whose steps no longer replay is BLOCKED and
    says where it stopped — its own steps have gone from the UI, which is a fact about
    the app worth reading, and it is emphatically not a pass. A scenario that files a new
    finding while it runs is FAILED regardless of what its oracle says. Only a scenario
    that ran to the end with nothing against it passes.
    """
    from .models import ReproSpec
    from .reverify import replay_spec

    before = set(session.record.findings)
    parsed = [parse_step(s) for s in scenario.steps]
    steps = [p for p in parsed if p is not None]
    unparsed = len(parsed) - len(steps)
    if not steps:
        return scenario.record_run(
            ScenarioStatus.BLOCKED, session_id=session.record.id,
            notes="no executable steps: none of this scenario's steps name an action "
                  "(write them as 'click \"Save\"' / 'type \"hi\"' / 'navigate to \"/cart\"')",
        )
    done, total = replay_spec(session, ReproSpec(steps=steps))
    new = [fid for fid in session.record.findings if fid not in before]
    if done < total:
        status, why = ScenarioStatus.BLOCKED, f"could not replay step {done + 1}/{total}"
    elif new:
        status, why = ScenarioStatus.FAILED, f"{len(new)} new finding(s) while walking it"
    else:
        status, why = _judge_scenario(session, scenario)
    if unparsed:
        why = f"{why} ({unparsed} step(s) were not instructions and were skipped)"
    return scenario.record_run(status, session_id=session.record.id, notes=why,
                               finding_ids=new)


def run_plan(config, repo_path: str, plan_id: str, surface=None,
             dev_command: str | None = None) -> dict:
    """Launch the app and walk a SAVED plan end to end — the re-runnable suite.

    This is what makes a plan worth persisting: after a change, one call re-drives the
    same scenarios against the new build and appends the result to each scenario's
    history, so the answer to "did I break the checkout flow" is a diff rather than a
    fresh act of invention. The session is always torn down, and the plan is always
    saved, including when a scenario blows up midway — a half-walked run is still the
    most recent thing known about those scenarios.
    """
    from .session import SessionManager

    plan = load_plan(config.trace_root, repo_path, plan_id, config.workspace_roots)
    if plan is None:
        return {"status": "not_run", "plan_id": plan_id,
                "error": f"no saved plan {plan_id!r} for {repo_path!r} — "
                         "call list_plans(repo_path) to see what is saved"}
    mgr = SessionManager(config)
    session = mgr.create(repo_path, surface, goal=f"re-run plan: {plan.goal}"[:200])
    sid = session.record.id
    try:
        try:
            ready = session.launch(dev_command)
        except Exception as exc:  # noqa: BLE001 - reported, never raised at the caller
            return {"status": "not_run", "plan_id": plan.id, "session_id": sid,
                    "error": f"launch failed: {str(exc)[:200]}"}
        if not ready:
            return {"status": "not_run", "plan_id": plan.id, "session_id": sid,
                    "error": "app did not become ready"}
        plan.begin_run(sid)
        try:
            for scenario in plan.scenarios:
                try:
                    run_scenario(session, scenario)
                except Exception as exc:  # noqa: BLE001 - one bad scenario is not the suite
                    scenario.record_run(ScenarioStatus.BLOCKED, session_id=sid,
                                        notes=f"scenario errored: {str(exc)[:200]}")
        finally:
            save_plan(config.trace_root, plan, config.workspace_roots)
        return {
            "status": "ran",
            "plan_id": plan.id,
            "session_id": sid,
            "goal": plan.goal,
            "runs": len(plan.runs),
            "totals": plan.totals(),
            "scenarios": [{"id": s.id, "title": s.title, "status": s.status.value,
                           "notes": s.notes, "finding_ids": s.finding_ids}
                          for s in plan.scenarios],
            "regressions": [{"id": s.id, "title": s.title} for s in plan.regressions()],
            "findings_total": len(session.record.findings),
        }
    finally:
        mgr.stop(sid)
