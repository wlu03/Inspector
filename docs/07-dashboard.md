# 07 — Dashboard

## Why it matters (more than it looks)

1. **It's the trust layer, and trust is the #1 adoption blocker.** The loop is inherently imperfect (oracle problem, reliability ceiling, false positives). An autonomous "no human in the loop" system that's sometimes wrong won't be trusted until it can be *audited*. A replay of "here's exactly what the agent clicked, what it saw, and why it called this a failure" is the most convincing artifact you can show.
2. **The data is already there.** Per [06](06-data-schema.md), each session records the action log, a screenshot per action, the log tap, and structured findings. The replay is a **view over artifacts already captured**, not new infrastructure.
3. **It's the commercial heart.** The MCP loop is assemblable from commodity parts (thin moat). The dashboard — run history, replays, flakiness trends, team sharing, sign-off — is the sticky, paid surface. Shape: **open plumbing, paid intelligence.**

## When it becomes essential

> The dashboard becomes essential the moment Inspector moves from **synchronous inner-loop** (developer watching the chat) to **autonomous / async / CI runs** (no human watching). Then there's no chat transcript to read — the dashboard is the primary interface and the safety valve that makes "no human blockage" acceptable, because a human can review after the fact.

In the pure IDE inner-loop, the host agent's chat *is* the UI and a dashboard is optional. So: **build it after the loop produces trustworthy data, and lead with it when the product moves toward CI/autonomous runs.**

## Views (mapped to existing artifacts)

| View | Shows | Backed by |
|---|---|---|
| **Run list** | session → surface, pass/fail, # findings, confidence, duration, PR link | `Run`, `Session` |
| **Replay timeline** (centerpiece) | scrub screenshot sequence; each frame annotated with the action + synced log lines | `trace/actions.jsonl` + `frames/` + `logs.jsonl` |
| **Finding detail** | summary, repro, expected vs actual, confidence, the exact frames where it broke, log evidence | `Finding` |
| **Trends** | flakiness (same test, different outcomes), regression history, "failed 3 of last 5 runs" | `Run` history |
| **Sign-off** | human-review surface for the PR-not-merge gate | `Finding.status`, `Run.pr_url` |

## Tech approach

- Pure frontend over the on-disk/remote trace format from [06](06-data-schema.md). No new capture.
- Replay = a scrubber over `actions.jsonl` that swaps the matching `frames/frame_NNNN.png` and highlights log lines by timestamp. For web, optionally layer rrweb for true DOM visual replay (but rrweb reconstructs, it doesn't re-execute).
- Hosted service reads from object storage; local mode reads from `~/.inspector/sessions/`.

## Sequencing

- **v0:** no dashboard — just write the trace artifacts to disk (schema in [06](06-data-schema.md)). ✅
- **v1 (built):** static aggregator — `inspector/dashboard/` scans `~/.inspector/sessions`, rolls up every run (pass-rate, severity, recurring-across-runs bugs) into one self-contained `dashboard.html` linking each session's replay; `python -m inspector.dashboard` or the `build_dashboard` MCP tool. Cross-session history + fix loop exposed via `list_runs` / `get_run` / `fix_finding` / `update_finding_status` (the host agent is the fixer). Styling shares `inspector/theme.py` with the landing page + replay. Replay video carries a cursor + click-intent overlay.
- **v2:** hosted dashboard with history, trends/flakiness, team sharing, sign-off, rrweb DOM replay, live E2B stream URL — the monetization surface, led when autonomous/CI runs land.
