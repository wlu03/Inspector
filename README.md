# Inspector

**An MCP server that lets a coding agent see, operate, and test the app it just built — across web, Electron, Android, and iOS — and feed structured, reproducible findings back so it can fix issues autonomously.**

Inspector plugs into Claude Code, Cursor, or any MCP-compatible coding agent. It spins up a sandbox, builds and launches the developer's app from its own dev command, and gives the agent **eyes and hands** on the live running build via **pure computer-use** (screenshot → ground → click → verify). The agent's existing assistant gains the ability to actually run and exercise the UI it writes — closing the loop between "wrote the code" and "knows it works." It is **multimodal by design**: the same loop runs on every surface.

---

## The three load-bearing theses

1. **Computer-use is the universal interaction layer.** Not Playwright (CDP/browser-bound, blind to native mobile). One pixel-level loop works on anything that opens on a screen.
2. **The MCP is the eyes and hands; the host coding agent is the brain and the fixer.** Inspector provides perception, action, detection, and the loop. The host agent decides and repairs.
3. **Acting is buildable; *judging* is hard.** Every deterministic signal (crash, console error, a11y violation, pixel diff) is buildable in weeks. Deciding "is this a real bug?" is research-hard — so we scope to reliable oracles and **never auto-merge**.

## Two architectural pillars

**1. Grounding lives in the host.** Because Inspector plugs into a frontier coding agent that *is already a strong vision-language model*, it does **not** host its own grounding LLM. It runs cheap element detection (OmniParser/YOLOv8) to produce a **Set-of-Mark** screenshot (numbered boxes over clickable elements), returns that to the host agent, and the host picks the element. Inspector maps the choice to coordinates and clicks. Grounding-by-ID beats raw-coordinate guessing and keeps Inspector lean (no GPU-hosted frontier model).

**2. Multimodal via one `SurfaceAdapter` interface.** Every surface — web, Electron, Android, iOS — is a concrete implementation of a single interface (`launch · is_ready · screenshot · input · logs · teardown`). The entire core (MCP tools, session manager, perception, action dispatcher, detection, trace, loop) is written **once** against that interface and never branches on surface type. Adding a surface = writing one adapter.

---

## Documentation index

| Doc | What's in it |
|---|---|
| [01 — Vision & Strategy](docs/01-vision-and-strategy.md) | Problem, users, the gap, competitive landscape, moat, strategic recommendation |
| [02 — Architecture](docs/02-architecture.md) | The `SurfaceAdapter` abstraction, system topology, the two execution planes, component map |
| [03 — MCP Contract](docs/03-mcp-contract.md) | Tool surface, session state machine, long-running Tasks pattern |
| [04 — Core Loop](docs/04-core-loop.md) | perceive→ground→act→verify, grounding-by-ID, action space, per-surface adapters |
| [05 — Detection & Feedback](docs/05-detection-and-feedback.md) | Issue detection, finding synthesis, reproducibility, loop guardrails |
| [06 — Data Schema](docs/06-data-schema.md) | Session / Action / Finding / Trace JSON — dashboard-ready from day one |
| [07 — Dashboard](docs/07-dashboard.md) | The trust + monetization layer: replays, pass/fail, history |
| [08 — Build Plan](docs/08-roadmap.md) | Full dev inventory: shared core + 4 adapters, milestones, bring-up order, effort |
| [09 — Risks & Open Questions](docs/09-risks-and-open-questions.md) | Risk register, hard constraints, decisions still open |
| [10 — Research Notes](docs/10-research-notes.md) | Sourced findings, benchmarks, tool inventory |
| [11 — Implementation Steps](docs/11-implementation-steps.md) | **Build-ready:** every part as ordered, concrete steps with exact APIs/commands |
| [12 — Accounts & Services](docs/12-accounts-and-services.md) | Every platform to sign up for, by phase (v0 needs only E2B + Replicate) |

## Status

**Planning.** No code yet.

**Scope (decided):** build **all four surfaces** (Web, Electron, Android, iOS) as a **personal/dev tool** — not productionizing yet (no hosting, payments, or hosted dashboard). Signups + build checklist for this scope: [12 — Accounts & Services](docs/12-accounts-and-services.md). Bring runtimes online web → Electron → Android → iOS (infra-readiness order; all four in scope).

Still open: whether this later becomes a product (the productization tier in [08](docs/08-roadmap.md) / [12](docs/12-accounts-and-services.md) is deferred, not cut), and whether to build on vs. compete with ScreenPipe/E2B/Swarm (see [01](docs/01-vision-and-strategy.md), [09](docs/09-risks-and-open-questions.md)).

## TL;DR build plan

Multimodal from day one: build the **surface-agnostic core + the `SurfaceAdapter` interface**, then the four adapters — **web, Electron, Android, iOS** — plug in without touching the core. Bring runtimes online in order of infra readiness (web/Electron share the Linux plane; Android adds Redroid; iOS needs a separate macOS plane). See [08 — Build Plan](docs/08-roadmap.md).

## Code (scaffold)

The Python package scaffold lives in [`loopback/`](loopback/):

```
loopback/
  server.py        # FastMCP server: launch_app / observe / act / verify / get_findings / stop
  session.py       # Session + SessionManager — the loop (observe → act → verify-after-act)
  sandbox.py       # E2B Desktop wrapper (lazy-imported)
  models.py        # Session / Element / Action / Finding / Run (pydantic)
  config.py
  adapters/        # SurfaceAdapter interface + web · electron · android · ios
  perception/      # OmniParser detector + Set-of-Mark renderer
  launch/          # framework detection + readiness
  detection.py  findings.py  trace.py  loop.py
```

**Status:** core + **Web** adapter wired; **Electron** partial (launch done, window-detection TODO); **Android/iOS** are interface skeletons (M2/M3). Heavy SDKs (fastmcp/e2b/replicate) are lazy-imported, so the package + pure tests run with only `pydantic` + `pillow`. Verified: all sources compile, 8 pure unit tests pass, core import graph loads without the cloud SDKs.

Quickstart:

```bash
pip install -e ".[all]"     # or ".[dev]" for tests only
cp .env.example .env        # add E2B_API_KEY + REPLICATE_API_TOKEN
pytest -q                   # pure unit tests (no cloud SDKs needed)
python -m loopback.server   # run the MCP server (stdio) — or wire via .mcp.json.example
```

Per-part build detail (exact APIs/commands) is in [11 — Implementation Steps](docs/11-implementation-steps.md).

### Repo layout

```
loopback/            # the package (core + adapters + perception + planes)
  planes/            # execution planes: LinuxPlane (E2B), MacOSPlane (tart, iOS), Redroid
infra/               # how each VM is provisioned (linux-e2b, android-redroid, macos-tart, ios-corellium)
examples/            # one buggy sample app per surface (web, electron, android, ios)
docs/                # 01–12 design docs
scripts/             # run_m0 / run_m0_mcp / run_app / doctor / probes
DELIVERABLES.md      # the full build checklist  ·  TESTING.md  # how to validate with a real agent
```

- **[DELIVERABLES.md](DELIVERABLES.md)** — the complete what's-needed checklist (multimodal).
- **[TESTING.md](TESTING.md)** — how to run tasks #6/#7 (validate with a real Claude Code agent).
- **[infra/](infra/)** — the two VM planes (Linux for web/Electron/Android, macOS for iOS).
