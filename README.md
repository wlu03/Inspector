# LoopBack

**An MCP server that lets a coding agent see, operate, and test the app it just built — across web, Electron, Android, and iOS — and feed structured, reproducible findings back so it can fix issues autonomously.**

LoopBack plugs into Claude Code, Cursor, or any MCP-compatible coding agent. It spins up a sandbox, builds and launches the developer's app from its own dev command, and gives the agent **eyes and hands** on the live running build via **pure computer-use** (screenshot → ground → click → verify). The agent's existing assistant gains the ability to actually run and exercise the UI it writes — closing the loop between "wrote the code" and "knows it works."

---

## The three load-bearing theses

1. **Computer-use is the universal interaction layer.** Not Playwright (CDP/browser-bound, blind to native mobile). One pixel-level loop works on anything that opens on a screen.
2. **The MCP is the eyes and hands; the host coding agent is the brain and the fixer.** LoopBack provides perception, action, detection, and the loop. The host agent decides and repairs.
3. **Acting is buildable; *judging* is hard.** Every deterministic signal (crash, console error, a11y violation, pixel diff) is buildable in weeks. Deciding "is this a real bug?" is research-hard — so we scope to reliable oracles and **never auto-merge**.

## The key architectural decision

Because LoopBack plugs into a frontier coding agent that *is already a strong vision-language model*, it does **not** host its own grounding LLM. It runs cheap element detection (OmniParser/YOLOv8) to produce a **Set-of-Mark** screenshot (numbered boxes over clickable elements), returns that to the host agent, and the host picks the element. LoopBack maps the choice to coordinates and clicks. Grounding-by-ID is far more reliable than raw-coordinate guessing, and this keeps LoopBack lean (no GPU-hosted frontier model).

---

## Documentation index

| Doc | What's in it |
|---|---|
| [01 — Vision & Strategy](docs/01-vision-and-strategy.md) | Problem, users, the gap, competitive landscape, moat, strategic recommendation |
| [02 — Architecture](docs/02-architecture.md) | System topology, the two execution planes, component map, deployment |
| [03 — MCP Contract](docs/03-mcp-contract.md) | Tool surface, session state machine, long-running Tasks pattern |
| [04 — Core Loop](docs/04-core-loop.md) | perceive→ground→act→verify, grounding-by-ID, action space, per-surface adapters |
| [05 — Detection & Feedback](docs/05-detection-and-feedback.md) | Issue detection, finding synthesis, reproducibility, loop guardrails |
| [06 — Data Schema](docs/06-data-schema.md) | Session / Action / Finding / Trace JSON — dashboard-ready from day one |
| [07 — Dashboard](docs/07-dashboard.md) | The trust + monetization layer: replays, pass/fail, history |
| [08 — Roadmap](docs/08-roadmap.md) | Phased build sequence, milestones, exit criteria, effort |
| [09 — Risks & Open Questions](docs/09-risks-and-open-questions.md) | Risk register, hard constraints, decisions still open |
| [10 — Research Notes](docs/10-research-notes.md) | Sourced findings, benchmarks, tool inventory |

## Status

**Planning.** No code yet. Two strategic decisions still open (see [01](docs/01-vision-and-strategy.md) and [09](docs/09-risks-and-open-questions.md)):
- **Tool vs. company** — personal dev tool, or venture bet? Changes the whole posture.
- **First surface** — recommendation is to lead with a differentiated surface (Electron/native or mobile), with web as table-stakes, *not* the headline.

## TL;DR build order

`v0` web + Electron, directed verification, deterministic oracles, PR-not-merge → `v1` Android + guardrails + replay → `v2` iOS + exploratory bug-finding + dashboard-led. See [08 — Roadmap](docs/08-roadmap.md).
