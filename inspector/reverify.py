"""Close the loop: after a fix lands, re-run a finding's repro against the new build
and report whether the bug is gone.

The recorded actions (actions.jsonl) ARE a deterministic re-run script — replay them
by coordinate on a freshly-launched session, then check whether the finding's signature
reappears. If it's gone, mark the finding fixed in the trace.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from .autopilot import collect_findings


def load_actions(session_dir: str) -> list[dict]:
    """Recorded actions from a prior session's actions.jsonl (the re-run script)."""
    path = os.path.join(session_dir, "actions.jsonl")
    out: list[dict] = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
    return out


def replay_actions(session, actions: list[dict]) -> int:
    """Re-drive recorded actions by coordinate against a fresh session. Returns the
    number of actions replayed (skips ones with no usable coordinate)."""
    from .models import ActionType
    n = 0
    for a in actions:
        try:
            t = ActionType(a.get("type", "wait"))
        except ValueError:
            continue
        coords = a.get("coords")
        if t in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.DRAG) and not coords:
            continue  # can't replay a click with no recorded coordinate
        try:
            session.act(t, coords=coords, text=a.get("text"), key=a.get("key"))
            n += 1
        except Exception:
            continue
    return n


def _norm_summary(s: str) -> str:
    return re.sub(r"\d+", "#", s or "").strip()[:120]


def signature_present(findings: list[dict], target_summary: str) -> bool:
    """Did a finding matching the target (digit-normalized summary) resurface?"""
    target = _norm_summary(target_summary)
    return any(_norm_summary(f.get("summary", "")) == target for f in findings)


def verify_fix(config, repo_path: str, prior_session_dir: str, target_summary: str,
               surface=None) -> dict:
    """Launch the (post-fix) app, replay the prior repro, and report fixed/still-present."""
    from .session import SessionManager
    mgr = SessionManager(config)
    session = mgr.create(repo_path, surface, goal=f"re-verify: {target_summary[:60]}")
    sid = session.record.id
    try:
        if not session.launch():
            return {"status": "error", "detail": "app did not become ready", "session_id": sid}
        replayed = replay_actions(session, load_actions(prior_session_dir))
        new = collect_findings(session)
        present = signature_present(new, target_summary)
        return {
            "status": "still_present" if present else "fixed",
            "reproduced": present,
            "actions_replayed": replayed,
            "new_findings": len(new),
            "session_id": sid,
        }
    finally:
        mgr.stop(sid)


def mark_fixed(session_dir: str, target_summary: str, fixed: bool) -> int:
    """Stamp matching findings in a trace's findings/ as fixed|still-open. Returns count."""
    fdir = os.path.join(session_dir, "findings")
    if not os.path.isdir(fdir):
        return 0
    target = _norm_summary(target_summary)
    n = 0
    for name in os.listdir(fdir):
        if not name.endswith(".json"):
            continue
        path = os.path.join(fdir, name)
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        if _norm_summary(d.get("summary", "")) == target:
            d["status"] = "fixed" if fixed else "open"
            with open(path, "w") as f:
                json.dump(d, f, indent=2)
            n += 1
    return n


def _find_by_label(elements, locator: str):
    """Re-find an element by its semantic label (exact, then contains). None if absent."""
    if not locator:
        return None
    t = locator.strip().lower()
    for e in elements:
        if (e.label or "").strip().lower() == t:
            return e
    for e in elements:
        if t and t in (e.label or "").lower():
            return e
    return None


@dataclass(frozen=True)
class ReplayOutcome:
    """What a replay achieved: how far through the steps it got, and whether it ever
    got to the screen the steps belong to.

    `unreachable` is the case that used to be invisible. A finding recorded two routes
    deep came back as "diverged at step 1", which reads as evidence about the app — the
    button is missing! — when the truth was that we never left the landing page. Those
    two have to be told apart before anything is judged, because only one of them says
    anything at all about the bug.
    """

    completed: int
    total: int
    unreachable: str = ""

    @property
    def reached(self) -> bool:
        """Whether the scenario's starting screen was actually reached."""
        return not self.unreachable

    @property
    def complete(self) -> bool:
        """Whether every step ran — the only state in which a verdict is worth reading."""
        return self.reached and self.completed >= self.total


def _preconditions(spec) -> dict[str, str]:
    """A spec's `k=v` preconditions as a mapping.

    `build_repro_spec` writes them as flat strings ("surface=web", "route=http://..."),
    and free-text ones are dropped here rather than guessed at: a precondition nothing
    can check must not silently become a precondition that was met.
    """
    out: dict[str, str] = {}
    for item in getattr(spec, "preconditions", None) or []:
        key, sep, value = str(item).partition("=")
        if sep and key.strip():
            out.setdefault(key.strip().lower(), value.strip())
    return out


def _current_url(session) -> str:
    """Where the fresh session actually is, as the browser sees it; '' when unreadable."""
    cdp = getattr(getattr(session, "adapter", None), "cdp", None)
    if cdp is None:
        return ""
    try:
        v = cdp.evaluate("window.location.href")
    except Exception:
        return ""
    return v.strip('"') if isinstance(v, str) else (v or "")


def _norm_url(url: str) -> str:
    return (url or "").strip().rstrip("#").rstrip("/")


def _base(url: str) -> str:
    """A URL without its query strings — path plus hash-route, which is what identifies
    a screen. The fragment keeps its own path because on an SPA the fragment IS the route."""
    head, _, frag = (url or "").strip().partition("#")
    head = head.split("?", 1)[0].rstrip("/")
    frag = frag.split("?", 1)[0].rstrip("/")
    return f"{head}#{frag}" if frag else head


def _route_step(current: str, route: str) -> str:
    """What to navigate to from where we are; '' means we are already there.

    A route that differs from the current document only by its fragment is turned into a
    bare '#...' move. That is what the app's own router listens for, it costs no page
    load — and it is the only navigation a packaged Electron shell survives, because
    there the document IS the app and replacing it kills the router that would route.
    """
    if _norm_url(current) == _norm_url(route):
        return ""
    if current and current.split("#", 1)[0] == route.split("#", 1)[0]:
        return "#" + (route.split("#", 1)[1] if "#" in route else "")
    return route


def _arrived(current: str, route: str) -> bool:
    """Whether the app really is on `route` after being sent there.

    Deliberately lenient: a query string the app appended, a trailing slash, a relative
    route recorded by hand all count as arrival. What it catches is the one case worth
    catching — being sent somewhere else entirely, which in practice means a guarded
    route bouncing an unauthenticated replay to the login screen. Replaying the steps
    there would judge a screen the finding was never about.
    """
    if not current:
        return True  # the surface cannot tell us; trust the navigation's own verdict
    here, there = _base(current), _base(route)
    if here == there or _norm_url(current) == _norm_url(route):
        return True
    return "://" not in route and here.endswith(there)


def reach_route(session, spec) -> str:
    """Put a freshly-launched session on the screen the finding was recorded on.

    Returns '' once we are there, else the reason we are not. ReproSpec has captured
    `route` since it was written and nothing ever used it, so any finding that wasn't on
    the landing page began replaying from the wrong screen: step 1 diverged, and
    re-verification reported `not_run` — an honest answer to a question nobody asked.
    Navigating first is what makes the rest of the replay mean anything.

    A surface that cannot navigate (a phone, an Electron file:// shell being sent to a
    different document) reports that it could not be reached instead of replaying where
    it happens to be, because a confident verdict from the wrong screen is worse than no
    verdict at all — it closes a bug that is still there.
    """
    from .models import ActionType

    pre = _preconditions(spec)
    want_surface = (getattr(spec, "surface", "") or "").strip() or pre.get("surface", "")
    here_surface = getattr(getattr(getattr(session, "record", None), "surface", None),
                           "value", "") or ""
    if want_surface and here_surface and want_surface != here_surface:
        return f"recorded on surface {want_surface!r}, replaying on {here_surface!r}"

    route = (getattr(spec, "route", "") or "").strip() or pre.get("route", "")
    if not route:
        return ""  # nothing was captured — replay from wherever the app boots, as before
    target = _route_step(_current_url(session), route)
    if not target:
        return ""  # the app already boots on that screen
    try:
        session.act(ActionType.NAVIGATE, url=target)
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised
        return f"{route} could not be opened on this surface ({str(exc)[:160]})"
    if not _arrived(_current_url(session), route):
        return f"navigating to {route} landed on {_current_url(session)} instead"
    return ""


def replay_spec(session, spec) -> ReplayOutcome:
    """Replay a ReproSpec on the current build: go to its route, then re-drive its steps
    by SEMANTIC locator (re-finding each element by label from the live observation)
    rather than by raw coordinates.

    Stops early when a step's element can't be found — the scenario diverged, and the
    outcome says how far it got so the caller can report that instead of a verdict.
    """
    from .models import ActionType

    steps = list(getattr(spec, "steps", []) or [])
    unreachable = reach_route(session, spec)
    if unreachable:
        return ReplayOutcome(0, len(steps), unreachable)
    valid = {t.value for t in ActionType}
    done = 0
    for step in steps:
        at = ActionType(step.action) if step.action in valid else ActionType.WAIT
        try:
            if at in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
                session.observe()
                el = _find_by_label(session.last_elements, step.locator)
                if el is None:
                    break  # scenario diverged -> not fully reached
                session.act(at, target_id=el.id)
            elif at == ActionType.TYPE:
                session.act(at, text=step.text)
            elif at == ActionType.KEY:
                session.act(at, key=step.key)
            elif at == ActionType.NAVIGATE:
                if not step.url:
                    break  # a navigate with nowhere to go can't be replayed
                session.act(at, url=step.url)
            elif at in (ActionType.BACK, ActionType.FORWARD, ActionType.RELOAD):
                session.act(at)
            done += 1
        except Exception:
            break
    return ReplayOutcome(done, len(steps))


def _eval_oracle(session, oracle) -> str | None:
    """Evaluate a ReproSpec oracle (the CORRECT behavior). pass -> fixed, fail ->
    still_present, inconclusive -> not_run. None when there is no oracle."""
    if not oracle:
        return None
    from .assertions import evaluate_assertions, summarize
    labels = {a.on for a in oracle if getattr(a, "on", "")}
    results = evaluate_assertions(oracle, **session.observation_context(labels))
    overall = summarize(results)["overall"]
    return {"pass": "fixed", "fail": "still_present"}.get(overall, "not_run")


def verify_fix_spec(config, repo_path: str, spec, target_summary: str, surface=None) -> dict:
    """Re-verify using the finding's ReproSpec: launch the current build, go to the route
    the bug was found on, replay the scenario by semantic locator, and judge by the
    explicit oracle (falling back to signature absence).

    Reports not_run when the scenario can't be reproduced — separately for a scenario
    that could not be REACHED (the route is gone, or this surface cannot navigate) and
    one that diverged part-way, because those point at different work: the first at the
    replay, the second at the app.
    """
    from .session import SessionManager

    mgr = SessionManager(config)
    session = mgr.create(repo_path, surface, goal=f"re-verify: {target_summary[:60]}")
    sid = session.record.id
    route = (getattr(spec, "route", "") or "")
    try:
        if not session.launch():
            return {"status": "not_run", "detail": "app did not become ready",
                    "session_id": sid}
        outcome = replay_spec(session, spec)
        done, total = outcome.completed, outcome.total
        if not outcome.reached:
            return {"status": "not_run",
                    "detail": f"could not reach the scenario: {outcome.unreachable}",
                    "route": route, "steps_replayed": 0, "steps_total": total,
                    "session_id": sid}
        if total and done < total:
            return {"status": "not_run",
                    "detail": f"scenario diverged at step {done + 1}/{total}",
                    "route": route, "steps_replayed": done, "steps_total": total,
                    "session_id": sid}
        oracle_status = _eval_oracle(session, getattr(spec, "oracle", None))
        if oracle_status is not None:
            return {"status": oracle_status, "oracle": True, "route": route,
                    "steps_replayed": done, "steps_total": total, "session_id": sid}
        new = collect_findings(session)
        present = signature_present(new, target_summary)
        return {"status": "still_present" if present else "fixed", "reproduced": present,
                "route": route, "steps_replayed": done, "steps_total": total,
                "new_findings": len(new), "session_id": sid}
    finally:
        mgr.stop(sid)
