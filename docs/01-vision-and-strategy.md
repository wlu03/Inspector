# 01 — Vision & Strategy

## The problem

Agentic coding exploded. The agent can *write* a UI but can't *see* whether it works. The feedback loop between "generated the code" and "confirmed it runs correctly" is still manual — a human launches the app, clicks around, and reports back. Existing automation (Playwright, Cypress) is browser-bound and can't reach native desktop or mobile, and it requires writing/maintaining test scripts rather than just *operating the live build*.

## What LoopBack is

An MCP server that gives any MCP-compatible coding agent the ability to:
1. Launch the developer's app in a sandbox from its own dev command (`npm run dev`, `expo start`, `electron .`).
2. Perceive and operate the live build via pure computer-use across web / Electron / Android / iOS.
3. Detect issues (crashes, errors, visual breakage) and return structured, reproducible findings.
4. Let the host agent fix the code and re-verify — autonomously, with a human only at the PR gate.

## Who it's for

Developers using agentic coding tools (Claude Code, Cursor, etc.). The buyer/champion is the developer who wants their agent to *finish the job* — to verify its own UI work instead of handing back untested code. A secondary, higher-budget framing is teams running autonomous/CI verification (see [07 — Dashboard](07-dashboard.md)).

## The gap / why now

- The substrate just matured: agent sandboxes with virtual desktops (E2B Desktop), cheap element detectors (OmniParser V2), and the MCP standard all landed in 2025–26.
- Every adjacent piece exists, but **nobody has packaged the exact combination**: sandbox + auto-build-and-launch + pure computer-use + cross-surface (incl. mobile) + structured feedback to the host coding agent.
- The native/mobile surfaces are genuinely underserved — the web-QA gold rush ($1.5B+ into AI testing startups) is almost entirely browser-focused.

## Competitive landscape

| Category | Players | Relationship to LoopBack |
|---|---|---|
| Agent sandbox + computer-use | **E2B Desktop**, EdgeBox, agent-sandbox | Generic blank desktop. We build on it; they don't know about *your project* or do detection/feedback. **Build-on or compete.** |
| Universal OS eyes+hands | **ScreenPipe** ("Playwright-like interface for the entire OS") | Closest to our pure-computer-use interaction layer. **Potential foundation or competitor — evaluate first.** |
| "Test my app from Claude Code" | **Swarm** (`dev_test` MCP, URL+goal, tunnels to dev server) | Closest to the *web slice*. Browser/URL-only, no computer-use, no mobile. Could extend toward us. |
| AI test agents for devs | **TestSprite, Qodo, Diffblue, Maisa** | Test-suite generators with MCP feedback loops. Code/browser-level, not computer-use on the live build. |
| Playwright/Chrome ecosystem | Playwright Agents, Chrome DevTools MCP | Strong on web; CDP/DOM-based (opposite approach). Microsoft-backed — do not compete head-on on web. |

## Moat analysis (honest)

- **The technology is assemblable from commodity parts** (sandbox = E2B, detection = OmniParser, action loop = standard CUA primitives, distribution = MCP). That makes v0 fast — and the moat thin.
- **Platform risk is the real threat.** The most reliable slice (web verification) is exactly where Microsoft and the coding-agent vendors are already moving. If LoopBack is "browser verification," it gets absorbed as a feature.
- **Defensible ground = the surfaces + the orchestration nobody integrates well:** auto-detecting/building/launching arbitrary dev builds, doing it across Electron/Android/iOS, and making the feedback genuinely actionable. Plus the dashboard/observability layer as the sticky, paid surface.

## Strategic recommendation

1. **Lead with a differentiated surface** (Electron/native desktop or mobile-during-dev), where Playwright/Chrome-DevTools-MCP can't reach and the labs are unlikely to bother. Support web as table stakes, never the headline.
2. **Scope ruthlessly to directed verification + deterministic oracles** first. Reliable, buildable in weeks, earns trust. Exploratory bug-hunting is a later moonshot.
3. **Treat the dashboard as the commercial heart**, not an add-on — "open plumbing, paid intelligence."
4. **Decide tool vs. company up front** — it changes everything (see below).

## Open strategic decisions

- **Tool or company?** A personal/learning tool is an unambiguous yes (high upside, low downside). A venture bet requires a real answer to "what when Cursor/Claude Code ships this natively?" — and the answer must be the native/mobile cross-surface wedge.
- **Which surface first?** Recommendation: not web. See [08 — Roadmap](08-roadmap.md).
- **Build on ScreenPipe / E2B, or around them?** Evaluate both before writing much code.
