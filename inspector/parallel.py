"""Fan-out verification: launch N headless autopilot agents IN PARALLEL, each scoped
to a different part of the frontend (a screen/feature/flow), then merge their findings.

Each agent gets its own isolated app instance (own sandbox / own Electron process on a
unique CDP port / own emulator), so they don't interfere. SessionManager is thread-safe,
so one manager fans the whole sweep out across a thread pool.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed


def plan_parts(config, repo_path: str, surface=None, goal: str = "find bugs") -> list[dict]:
    """The PLANNER: launch a short-lived scout session, look at the app's first screen,
    and have the brain decompose it into the distinct parts to test in parallel.

    Returns [{name, goal}]; falls back to a single whole-app part if planning fails."""
    from .driver import get_driver
    from .session import SessionManager

    mgr = SessionManager(config)
    session = mgr.create(repo_path, surface, goal="plan: map the app into parts")
    sid = session.record.id
    try:
        if not session.launch():
            return [{"name": "app", "goal": goal}]
        som, elements, _ = session.observe()
        parts = get_driver(config).plan(som, elements, goal)
        return parts or [{"name": "app", "goal": goal}]
    except Exception:
        return [{"name": "app", "goal": goal}]
    finally:
        mgr.stop(sid)


def verify_part(mgr, config, repo_path: str, part: dict, surface=None, max_steps: int = 6) -> dict:
    """One headless agent: launch its own app instance, drive it toward `part`'s goal,
    return that part's findings. Always tears its instance down + writes a replay."""
    from .autopilot import run_autopilot
    from .driver import get_driver

    name = part.get("name", "part")
    goal = part.get("goal", f"test the {name}")
    session = mgr.create(repo_path, surface, goal=goal)
    sid = session.record.id
    try:
        session.record.alias = name
    except Exception:
        pass
    try:
        if not session.launch():
            return {"part": name, "status": "error", "detail": "app not ready", "session_id": sid}
        report = run_autopilot(session, get_driver(config), goal, max_steps)
        return {
            "part": name, "status": "ok", "session_id": sid,
            "steps": report.get("steps", 0),
            "findings_total": report.get("findings_total", 0),
            "findings": report.get("findings", []),
        }
    except Exception as exc:  # noqa: BLE001 - one part failing must not sink the sweep
        return {"part": name, "status": "error", "detail": str(exc)[:200], "session_id": sid}
    finally:
        try:
            from .replay import write_replay_html, write_replay_video
            session.trace.save_session(session.record)
            write_replay_video(session.trace.dir)
            write_replay_html(session.trace.dir)
        except Exception:
            pass
        mgr.stop(sid)


def parallel_verify(config, repo_path: str, parts: list[dict], surface=None,
                    max_steps: int = 6, max_workers: int = 4) -> dict:
    """Run an autopilot agent per part concurrently; merge the findings.

    `parts` = [{"name": "settings", "goal": "test the Settings screen ..."}, ...].
    Returns per-part results + a merged finding list (de-duped by summary).
    """
    from .session import SessionManager
    mgr = SessionManager(config)
    results: list[dict] = []
    workers = max(1, min(max_workers, len(parts)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(verify_part, mgr, config, repo_path, p, surface, max_steps) for p in parts]
        for f in as_completed(futs):
            results.append(f.result())

    results.sort(key=lambda r: r.get("part", ""))
    merged, seen = [], set()
    for r in results:
        for fin in r.get("findings", []):
            key = (fin.get("summary") or "").strip().lower()[:120]
            if key and key not in seen:
                seen.add(key)
                merged.append(fin)
    return {
        "parts": [{k: r[k] for k in r if k != "findings"} for r in results],
        "agents": len(parts),
        "merged_findings": merged,
        "total_unique_findings": len(merged),
    }


def planned_verify(config, repo_path: str, surface=None, goal: str = "find bugs",
                   max_steps: int = 5, max_agents: int = 4) -> dict:
    """Plan → dispatch → merge: the planner maps the app into parts, then a headless
    agent per part traverses it in parallel. The one-call multi-agent sweep."""
    parts = plan_parts(config, repo_path, surface, goal)[:max_agents]
    # iOS: the scout (plan_parts) already built the .app, and N concurrent xcodebuilds
    # would contend on the shared derivedData — so the fan-out agents reuse that build.
    if str(getattr(surface, "value", surface) or "").lower() == "ios":
        import os
        os.environ["INSPECTOR_IOS_PREBUILT"] = "1"
    result = parallel_verify(config, repo_path, parts, surface, max_steps, max_workers=max_agents)
    result["plan"] = parts
    try:
        from .parallel_report import write_parallel_report
        result["parallel_report"] = write_parallel_report(
            config.trace_root, parts, result["parts"], result["merged_findings"])
    except Exception:
        pass
    return result
