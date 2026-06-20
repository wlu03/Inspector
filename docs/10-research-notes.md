# 10 — Research Notes

Sourced findings behind the plan. Dates reflect the 2026 research window.

## Sandbox / runtime substrate
- **E2B Desktop Sandbox** — Ubuntu 22.04 + XFCE + VNC; purpose-built for LLM computer-use. SDK (Python + JS) exposes `screenshot()`, `left/double/right_click`, `move_mouse`, `drag`, `scroll`, `write`, `press` (xdotool + scrot under the hood). [github.com/e2b-dev/desktop](https://github.com/e2b-dev/desktop) · [docs](https://e2b.dev/docs/use-cases/computer-use)
- Alternatives: Daytona, Firecracker microVMs, Sprites.dev (checkpoint/rollback), EdgeBox, agent-sandbox. [Northflank](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes)
- **iOS hard wall:** simulator is macOS-only (runs app as native macOS process vs iOS frameworks). Non-Mac options: Corellium (virtualized iOS), device farms (BrowserStack, Sauce, AWS Device Farm, Appetize). [iOS Simulators guide](https://codersera.com/blog/ios-simulators-complete-guide-2026/)
- **Android without KVM:** Redroid (Android as a container process tree), great on ARM64/Graviton. [Android emulator in Docker without KVM](https://codersera.com/blog/android-emulator-docker-without-kvm/)

## Perception / grounding
- **OmniParser V2** (Microsoft) — YOLOv8 detects interactive elements + Florence-2 captions; turns any LLM into a computer-use agent. [Microsoft Research](https://www.microsoft.com/en-us/research/articles/omniparser-v2-turning-any-llm-into-a-computer-use-agent/) · [paper](https://arxiv.org/pdf/2408.00203)
- **Set-of-Mark** — overlay numbered bboxes so the model grounds to an ID, not an (x,y). [OmniParser writeup](https://learnopencv.com/omniparser-vision-based-gui-agent/)
- **UI-TARS** — end-to-end GUI grounding model; unified action space. Upgrade path from SoM.
- **Action space** — 8 primitives: mouse_move, click, drag, scroll, press_keys, type_text, wait, finish.

## Reliability / benchmarks
- Computer use: Claude ~78% OSWorld, OpenAI Operator ~38%. "3 of 4 tasks fail first try" at the good end. [Claude vs OpenAI](https://www.digitalapplied.com/blog/computer-use-agents-2026-claude-openai-gemini-matrix)
- GUI grounding on dense pro UIs: ScreenSpot-Pro top ~18.9%; GPT-4o <2% on dense small targets. [ScreenSpot-Pro](https://arxiv.org/html/2504.07981v1)
- Realistic web tasks (Online-Mind2Web): Operator 61%, Claude 56% — ~30pt below WebVoyager claims. Benchmark inflation is real.
- **Oracle problem:** LLM-as-bug-judge ~31% precision; proactive-bug benchmark TestExplora best <16% Fail-to-Pass. [TestExplora](https://arxiv.org/html/2602.10471v2)
- Flakiness: Google ~16% of 4.2M tests flaky; ~84% of pass→fail transitions involve a flaky test. [Google](https://research.google.com/pubs/archive/45880.pdf)
- Automated a11y catches ~57% of issues by volume but only ~29.5% of WCAG criteria fully. [Deque](https://www.deque.com/blog/automated-testing-study-identifies-57-percent-of-digital-accessibility-issues/)

## Launch / readiness
- **wait-on** (ports/sockets/http 2xx), **detect-port**, **start-server-and-test**, **npm-dev-mcp** (auto-discovers package.json dev scripts; tracks ports via lsof/netstat). [wait-on](https://socket.dev/npm/package/wait-on) · [npm-dev-mcp](https://glama.ai/mcp/servers/@masamunet/npm-dev-mcp)

## MCP
- **Tasks primitive** (2025-11-25 spec): call-now/fetch-later; `taskId` + poll `tasks/get`; states working/input_required/completed/failed/cancelled; reuses `progressToken`. Treat `tasks/get` as authoritative. [WorkOS](https://workos.com/blog/mcp-async-tasks-ai-agent-workflows) · [SEP-1391](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1391)
- **FastMCP** progress monitoring. [gofastmcp](https://gofastmcp.com/v2/clients/progress)

## Feedback / repro / loop
- **Verifier-in-the-loop** beats self-critique (Reflexion 91% vs 80% pass@1). Sentry Seer: 94.5% root-cause accuracy with reproduce→patch→re-run.
- **rrweb** records DOM mutations for visual replay but *reconstructs, doesn't re-execute* — cannot verify a fix. Use action-log replay for verification.
- **Guardrails:** hard caps (LangGraph recursion_limit), no-progress via output hashing, K-sample self-consistency over verbalized confidence, PR-not-merge as terminal HITL.

## Closest existing products (competitive)
- **E2B Desktop + MCP** — generic computer-use sandbox; not project-aware. [github](https://github.com/e2b-dev/desktop)
- **ScreenPipe** — "Playwright-like interface for the entire OS"; eyes+hands on any desktop app. Foundation or competitor.
- **Swarm** — `dev_test` MCP: URL+goal, tunnels to dev server. Closest to the web slice. [useswarm.co](https://www.useswarm.co/blog/how-to-test-your-app-from-claude-code-with-mcp)
- **TestSprite / Qodo / Diffblue / Maisa** — AI test agents with MCP feedback loops; test-suite-generation flavored, not computer-use on the live build.
- **Electron MCP servers** — CDP-based (opposite approach to pure computer-use).
