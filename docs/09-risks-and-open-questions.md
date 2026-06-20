# 09 — Risks & Open Questions

## Hard constraints (non-negotiable physics/economics)

1. **iOS = macOS wall.** The iOS Simulator runs your app as a native macOS process against iOS frameworks — it **cannot** run in a Linux container. iOS is always a separate, costlier macOS-hosted plane (cloud Mac / Corellium / device farm). Architect for two planes from day one.
2. **Computer-use reliability ceiling.** Best-in-class computer use ~78% on OSWorld; GUI grounding on dense pro UIs as low as ~19% (and <2% raw-coordinate for small targets). → grounding-by-ID + verify-after-act, never raw pixel-guessing as the default.
3. **The oracle problem.** Autonomous *functional* bug-finding is research-hard (best models <16% on proactive-bug benchmarks; LLM-as-judge ~31% precision). → deterministic oracles are authoritative; scope exploratory to crash/invariant; never auto-merge.
4. **Flakiness is endemic.** ~16% of large test suites are flaky; LLM agents are non-deterministic even at temp 0. → determinism controls (seed, clock, HAR) are mandatory, not optional.
5. **Token cost.** Screenshots are token-heavy for the host. → prefer the SoM element *list* (text) over full images where possible; cost caps per session.

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| **Thin moat** — assembled from commodity parts | High | Differentiate on cross-surface + orchestration + dashboard; don't lead on web |
| **Platform risk** — Cursor/Claude Code/Microsoft ship this natively | High | Own the native/mobile surfaces they won't prioritize; be best at dev-loop integration |
| Readiness detection brittle across frameworks | Med | Compose multiple signals; allow explicit `dev_command`; iterate on a corpus of real projects |
| Detector misses custom/canvas elements | Med | Coords fallback; UI-TARS upgrade; verify-after-act catches failed clicks |
| False positives erode trust | High | Confidence gating, deterministic-first, replay dashboard for audit, PR-not-merge |
| iOS cost/complexity sinks timeline | Med | Defer to v2; treat as premium add-on |
| MCP Tasks primitive immaturity | Low | Polling fallback |
| Competitor (Swarm/E2B/ScreenPipe) extends into the gap first | Med | Move fast on the differentiated wedge; evaluate build-on vs compete early |

## Open questions / decisions to make

- [ ] **Tool or company?** Personal/learning tool = clear yes. Venture = needs a real answer to platform risk. *Decide before scaling effort.*
- [ ] **First surface?** Recommendation: lead with a differentiated surface (Electron/native or mobile), web as table stakes. *Confirm.*
- [ ] **Build on ScreenPipe / E2B, or around them?** Evaluate both before writing much code — ScreenPipe may be the interaction foundation or a competitor.
- [ ] **Detection scope for v0** — strictly directed verification + deterministic oracles? (Recommended yes.)
- [ ] **Grounding model** — OmniParser SoM only, or include UI-TARS from the start?
- [ ] **Language/SDK** — Python (FastMCP) vs TS, driven by detector + E2B SDK ergonomics.
- [ ] **Hosting model** — local-first package vs hosted service first? (Affects dashboard timing.)

## Pre-build validation (do before writing much code)

1. Try **Swarm** and **E2B Desktop's MCP** — they're the closest; using them reveals exactly what's missing.
2. Evaluate **ScreenPipe** — foundation or competitor?
3. Spike the **grounding-by-ID loop** on one web app to confirm host-decides + SoM + verify-after-act is reliable enough to build on.
