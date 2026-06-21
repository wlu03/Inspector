# Inspector

**An MCP server that lets a coding agent see, operate, and test the app it just built — across web, Electron, Android, and iOS — and feed structured, reproducible findings back so it can fix issues autonomously.**

Inspector plugs into Claude Code, Cursor, or any MCP-compatible coding agent. It spins up a sandbox, builds and launches the developer's app from its own dev command, and gives the agent **eyes and hands** on the live running build via **pure computer-use** (screenshot → ground → click → verify). The agent's existing assistant gains the ability to actually run and exercise the UI it writes — closing the loop between "wrote the code" and "knows it works." It is **multimodal by design**: the same loop runs on every surface.

---

## Why Inspector exists — the gap in today's tooling

A coding agent can write a UI but can't *see* whether it works. The existing ways to give it eyes each break down in a specific, structural way. Inspector is built to keep what each does well and fix what it doesn't.

### 1. Raw computer-use (Claude computer-use driving a screen)

The model takes a screenshot and emits raw `(x, y)` coordinates. Powerful and universal, but:

- **Imprecise grounding.** Clicking by guessed pixel coordinates misfires on dense layouts, small targets, and scaled/retina displays — the single biggest source of "the agent clicked the wrong thing."
- **Pixels only, no structured evidence.** It can't read the DOM, the accessibility tree, console errors, failed network requests, or run axe-core. "Looks fine" is a vision *guess*, never a deterministic pass/fail.
- **Slow and token-heavy.** Every step is full-screenshot → model → action; multi-step flows burn image tokens and wall-clock.
- **Non-reproducible.** Vision-driven clicks vary run to run; there's no clean repro trail or replay, so a failure rarely becomes a regression test.
- **Unsafe by default.** It drives the *real* desktop unless you build the isolation, launch orchestration, and teardown yourself.
- **Confirmatory bias.** Asked to "check the app," a general agent tends to confirm it works rather than try to break it.

### 2. Browser-based computer-use (cloud-browser agents)

Same coordinate/heuristic fragility as above, plus:

- **Web-only.** Bound to a browser — blind to native Android/iOS, Electron desktop chrome, OS dialogs, and file pickers.
- **No source link.** A bug it sees can't be tied back to `file:line` in your repo.
- **Hosted/opaque.** You usually don't control the environment, determinism, or data egress.

### 3. Playwright-class systems (Playwright MCP, Browserbase ui-test, Stagehand, Appium-style)

These give the deterministic rigor computer-use lacks — and ui-test in particular has an excellent adversarial methodology we deliberately borrow from — but they're structurally constrained:

- **CDP/browser-bound.** Playwright speaks the Chrome DevTools Protocol: it drives web and the Electron renderer only. **Native mobile means switching tools entirely** (Appium/XCUITest/Espresso) — different selectors, different infra, no single loop across surfaces.
- **Selector-bound, so blind spots.** It tests the *DOM*, not the rendered pixels: canvas/WebGL, charts, maps, games, `<iframe>`/shadow-DOM content are opaque, and selectors break on markup churn.
- **DOM-present ≠ user-visible.** A button that exists in the DOM but is clipped, z-index-hidden, off-screen, or invisibly low-contrast can *pass* DOM assertions while being broken to a human. It validates the document, not the experience.
- **An executor, not a brain.** It runs scripts; deciding what to test and adapting mid-run is a layer you add on top, and mapping a runtime failure to your source isn't built in.

### How Inspector closes the gap

Inspector keeps computer-use's **universality** and Playwright's **deterministic rigor**, driven by a frontier coding agent as the **brain**, inside isolated **VMs**, producing **reproducible, source-linked** findings — and it's **adversarial by default**:

- **One loop, every surface.** A single `SurfaceAdapter` interface runs the same observe→act→verify loop on web, Electron, Android, and iOS. Pixel-level computer-use reaches canvas/WebGL/native that DOM selectors can't.
- **Grounding-by-ID, not raw coordinates.** Cheap element detection (OmniParser) renders a **Set-of-Mark** screenshot — numbered boxes over interactive elements. The host agent picks an *id*; Inspector maps it to coordinates and clicks. This removes the misclick failure mode of coordinate-guessing.
- **Hybrid evidence — pixels *and* a deterministic channel.** `audit_dom` injects **axe-core** over CDP and reads structured facts straight off the live DOM (WCAG violations, broken images via `naturalWidth=0`, unlabeled inputs), alongside a console/exception log-tap — recovering Playwright/ui-test's strongest evidence tier *where a DOM exists*, while vision still catches the visual breakage the DOM can't show. Best of both, not either/or.
- **Source-linked findings.** A source scan + missing-element oracle ties a runtime absence back to `file:line`, and every finding carries a repro trail — so the agent can go straight to the fix.
- **Adversarial by design.** Three-round planning (functional → adversarial → coverage) and a per-feature attack catalog push edge inputs (empty/XSS/overflow/unicode), rapid double-submit, Escape/keyboard nav, bogus routes, and mobile-viewport overflow. The mandate is *try to break it, not confirm it works.*
- **Isolated, with lifecycle.** Apps run in VMs (E2B) with launch/readiness orchestration, an idle reaper, and teardown — safe by construction, no real desktop at risk.
- **Reproducible & fix-closing.** Every run writes a trace (frames + `actions.jsonl` + logs) → replay (HTML + video), and findings move `open → fixed → verified` so a vision-found failure becomes a re-runnable check.
- **Lean brain/hands split.** The host frontier agent is the brain (no GPU-hosted model to run), and a host-token-cost mode caps full images per session to control the per-step cost that plagues raw computer-use.

| | Raw computer-use | Browser computer-use | Playwright-class | **Inspector** |
|---|:--:|:--:|:--:|:--:|
| Web | ✅ | ✅ | ✅ | ✅ |
| Electron / native mobile | ⚠️ ad-hoc | ❌ | ❌ (separate tools) | ✅ one loop |
| Canvas / WebGL / pixel-only UI | ✅ | ✅ | ❌ | ✅ |
| Deterministic checks (axe, console, images) | ❌ | ❌ | ✅ | ✅ |
| Sees visual breakage (clipped/hidden/contrast) | ✅ | ✅ | ❌ | ✅ |
| Precise grounding | ❌ coords | ❌ coords | ✅ selectors | ✅ by-ID |
| Source-linked findings (`file:line`) | ❌ | ❌ | ❌ | ✅ |
| Reproducible trace + replay | ❌ | ❌ | ✅ | ✅ |
| Adversarial by default | ❌ | ❌ | ⚠️ if scripted | ✅ |
| Isolated sandbox + lifecycle | ❌ DIY | ⚠️ hosted | ⚠️ varies | ✅ |

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
| [13 — Agentic Test Loop](docs/13-agentic-test-loop.md) | Plan-driven QA loop: `set_plan / update_scenario / test_report` + the `run_test_session` prompt |

## Status

**Building.** Web surface is end-to-end live-proven; pure-Python core, 13+ MCP tools, deterministic `audit_dom`, adversarial planning, and findings/replay are wired (100+ unit tests). Electron is one refactor out; Android/iOS adapters are interface skeletons. See [BUILD_PLAN.md](BUILD_PLAN.md) for the authoritative status.

**Scope (decided):** build **all four surfaces** (Web, Electron, Android, iOS) as a **personal/dev tool** — not productionizing yet (no hosting, payments, or hosted dashboard). Signups + build checklist for this scope: [12 — Accounts & Services](docs/12-accounts-and-services.md). Bring runtimes online web → Electron → Android → iOS (infra-readiness order; all four in scope).

Still open: whether this later becomes a product (the productization tier in [08](docs/08-roadmap.md) / [12](docs/12-accounts-and-services.md) is deferred, not cut), and whether to build on vs. compete with ScreenPipe/E2B/Swarm (see [01](docs/01-vision-and-strategy.md), [09](docs/09-risks-and-open-questions.md)).

## TL;DR build plan

Multimodal from day one: build the **surface-agnostic core + the `SurfaceAdapter` interface**, then the four adapters — **web, Electron, Android, iOS** — plug in without touching the core. Bring runtimes online in order of infra readiness (web/Electron share the Linux plane; Android adds Redroid; iOS needs a separate macOS plane). See [08 — Build Plan](docs/08-roadmap.md).

## Code (scaffold)

The Python package scaffold lives in [`inspector/`](inspector/):

```
inspector/
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
python -m inspector.server   # run the MCP server (stdio) — or wire via .mcp.json.example
```

Per-part build detail (exact APIs/commands) is in [11 — Implementation Steps](docs/11-implementation-steps.md).

### Repo layout

```
inspector/            # the package (core + adapters + perception + planes)
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
