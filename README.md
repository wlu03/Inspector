# Inspector

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![MCP](https://img.shields.io/badge/protocol-MCP-6f42c1.svg)
![Surfaces](https://img.shields.io/badge/surfaces-web%20%7C%20electron%20%7C%20android%20%7C%20ios-0aa.svg)
![Status](https://img.shields.io/badge/status-building-orange.svg)
![Tests](https://img.shields.io/badge/tests-100%2B-green.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
[![Docs](https://img.shields.io/badge/docs-DeepWiki-1f6feb.svg)](https://deepwiki.com/wlu03/Inspector/)

**An MCP server that lets your coding agent see, click, and test the app it just built, then hand back reproducible findings so it can fix bugs on its own. Works on web, Electron, Android, and iOS.**

Inspector plugs into Claude Code, Cursor, or any MCP coding agent. It spins up a sandbox, launches your app with your own dev command, and gives the agent real eyes and hands: screenshot, find the element, click, verify. One loop, every surface.

## What makes it good

- **One loop for every surface.** A single `SurfaceAdapter` runs the same observe, act, verify loop on web, Electron, Android, and iOS. Pixel-level computer-use reaches canvas, WebGL, and native UI that DOM selectors can't touch.
- **Clicks that land.** Cheap element detection numbers every interactive element (Set-of-Mark). The agent picks an id, Inspector clicks it. No more misfired coordinate guesses.
- **Hard evidence, not vibes.** `audit_dom` runs axe-core over the live DOM for real pass/fail on accessibility, broken images, and unlabeled inputs, while vision still catches the visual breakage the DOM hides.
- **Findings point at your code.** Every bug ties back to `file:line` with a repro trail, so the agent goes straight to the fix.
- **Built to break things.** Three rounds of planning and a per-feature attack catalog push edge inputs, double-submits, keyboard nav, bad routes, and mobile overflow. The goal is to break the app, not confirm it works.
- **Safe and reproducible.** Apps run in isolated VMs with full lifecycle. Every run writes a trace that replays as HTML and video, and findings move `open` to `fixed` to `verified`.

## How it compares

| | Raw computer-use | Browser agents | Playwright-class | **Inspector** |
|---|:--:|:--:|:--:|:--:|
| Web | ✅ | ✅ | ✅ | ✅ |
| Electron / native mobile | ⚠️ | ❌ | ❌ | ✅ one loop |
| Canvas / WebGL / pixel-only UI | ✅ | ✅ | ❌ | ✅ |
| Deterministic checks (axe, console) | ❌ | ❌ | ✅ | ✅ |
| Sees visual breakage | ✅ | ✅ | ❌ | ✅ |
| Precise clicks | ❌ | ❌ | ✅ | ✅ |
| Findings link to source | ❌ | ❌ | ❌ | ✅ |
| Reproducible replay | ❌ | ❌ | ✅ | ✅ |
| Adversarial by default | ❌ | ❌ | ⚠️ | ✅ |
| Isolated sandbox | ❌ | ⚠️ | ⚠️ | ✅ |

## Status

Web is live and proven end to end. Pure-Python core with 13+ MCP tools, `audit_dom`, adversarial planning, and findings plus replay (100+ tests). Electron is one refactor out; Android and iOS adapters are in progress. All four surfaces are in scope as a personal dev tool (no hosting or payments yet).

## Quickstart

```bash
pip install -e ".[dev]"     # runtime plus dev tools
cp .env.example .env        # set REPLICATE_API_TOKEN; E2B_API_KEY optional
inspector-mcp doctor        # verify env and keys
inspector-mcp serve         # run the MCP server (stdio)
pytest -q                   # unit tests
```

## Layout

```
inspector/     # core plus adapters (web, electron, android, ios) plus perception
infra/         # how each VM is provisioned
examples/      # one buggy sample app per surface
docs/          # design docs 01 through 13
scripts/       # run helpers, doctor, probes
```

## Docs

**Browsable docs: [deepwiki.com/wlu03/Inspector](https://deepwiki.com/wlu03/Inspector/)** for a searchable, auto-generated overview of the whole codebase.

Full design docs also live in [`docs/`](docs/), covering vision, architecture, the MCP contract, the core loop, detection, data schema, roadmap, and the agentic test loop. Start with [01. Vision & Strategy](docs/01-vision-and-strategy.md) and [08. Build Plan](docs/08-roadmap.md). See [TESTING.md](TESTING.md) to validate with a real Claude Code agent.
