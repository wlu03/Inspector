# 13 — Agentic test loop

How Inspector runs as a **plan-driven QA agent** instead of ad-hoc command calls.
The host agent (Claude Code / Cursor) is still the brain — this layer gives it an
*overall plan* and a *loop discipline* so it tests the app systematically.

## The loop

```
launch → observe → set_plan → ┌─ per scenario ─────────────────┐ → test_report
                              │ observe → act → verify →        │
                              │ update_scenario  (adapt plan)   │
                              └─────────────────────────────────┘
```

1. **`launch_app`** then **`observe`** — understand the app.
2. **`set_plan(goal, scenarios)`** — draft 3–7 scenarios covering the *different parts*
   (each flow/form, navigation, edge cases, AI features). Each scenario:
   `{title, rationale, steps, expected}`.
3. **Work each scenario**: `observe → act → verify → get_findings → update_scenario`.
   Discover a new feature mid-run? Call `set_plan` again to **adapt**.
4. **`test_report()`** — per-scenario status + notes + findings + totals.

## Tools (added)
- `set_plan(session_id, goal, scenarios)` — record the overall plan.
- `update_scenario(session_id, scenario_id, status, notes, finding_ids)` — record a result.
- `test_report(session_id)` — the full run summary.

(Plus the primitives: `launch_app · observe · act · verify · get_findings · stop`.)

## How to trigger the loop

**Option A — the MCP prompt (recommended).** Inspector ships an MCP *prompt*
`run_test_session(repo_path, goal)` that injects the full protocol. In Claude Code
it appears as a slash command (e.g. `/inspector:run_test_session`) — pick it, fill in
the repo path + goal, and the agent runs the planned loop.

**Option B — paste a prompt.** Tell the agent:
> Use the **inspector** MCP tools to test `<repo_path>` as a planning QA agent: launch,
> observe, `set_plan` with 3–7 scenarios covering the different parts, then for each run
> observe→act→verify→`update_scenario`, adapting the plan as you discover features, and
> finish with `test_report`. Report findings (with file:line) and recommended fixes.

## Artifacts
The plan is persisted to `plan.json` in the session trace; `test_report()` returns the
structured run. (Surfacing the plan in the replay UI is a follow-up.)
