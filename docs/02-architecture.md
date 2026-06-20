# 02 — Architecture

## The decision that shapes everything: where grounding lives

Inspector plugs into a frontier coding agent that is **already a strong vision-language model**. So Inspector does **not** host its own grounding LLM. Instead:

> Inspector runs cheap **element detection** (OmniParser-style YOLOv8 + Florence-2 captions) to produce a **Set-of-Mark** screenshot — numbered boxes over clickable elements — and returns that + the element list to the host agent. The **host agent picks element #N**; Inspector maps #N → bbox center → click.

Benefits: no GPU-hosted frontier model, grounding-by-ID is far more reliable than raw-coordinate guessing (which scores <2% on dense UIs), and it cleanly realizes "MCP = eyes+hands, host = brain."

## The multimodal abstraction: one `SurfaceAdapter` interface

Inspector is multimodal across **web, Electron, Android, and iOS** by design. The loop stays identical across surfaces because each surface is a concrete implementation of a single interface — the core never branches on surface type:

```
SurfaceAdapter:
   launch(repo)        # boot the app in its runtime
   is_ready() -> bool  # interactive yet?
   screenshot() -> png
   input(action)       # click / type / tap / swipe
   logs() -> stream    # crash / error signal
   teardown()
```

Adding a surface = writing one adapter. The MCP tools, session manager, perception (detector→SoM), action dispatcher, detection engine, trace recorder, and loop controller are all written **once** against this interface. See [04 — Core Loop](04-core-loop.md) for each adapter's backend and [08 — Build Plan](08-roadmap.md) for the full inventory.

## System topology

```
┌─────────────────────────────────────────────────────────────────┐
│  HOST CODING AGENT  (Claude Code / Cursor / any MCP client)       │
│  calls tools · sees SoM screenshots · decides actions · fixes code│
└───────────────────────────────┬───────────────────────────────────┘
                                 │  MCP (stdio / streamable HTTP)
                                 │  Tasks pattern: call-now / fetch-later
┌────────────────────────────────▼──────────────────────────────────┐
│  CONTROL PLANE — Inspector MCP server + Orchestrator                 │
│  • MCP tool layer (launch / observe / act / verify / report / stop)│
│  • Session manager (handles, state machine, task IDs)              │
│  • Element detector service (OmniParser/YOLOv8 → Set-of-Mark)      │
│  • Detection engine (log parse, visual-diff, error classify)      │
│  • Finding store + replay-trace recorder                          │
│  • Loop controller + guardrails                                   │
└───────┬────────────────────────────────────────┬──────────────────┘
        │ provisions / drives                     │ (iOS only)
┌───────▼──────────────────────────┐   ┌──────────▼──────────────────┐
│  EXECUTION PLANE — Linux sandbox  │   │  EXECUTION PLANE — macOS host │
│  (E2B Desktop / Firecracker)      │   │  (cloud Mac / Corellium)      │
│  • XFCE desktop + VNC             │   │  • iOS Simulator              │
│  • Launch adapter runs the app    │   │  • simctl / idb: screenshot,  │
│  • screenshot (scrot)             │   │    tap, type                  │
│  • input (xdotool)                │   │  • idevicesyslog (log tap)    │
│  • web / Electron / Android(Redroid)│ └───────────────────────────────┘
│  • Log tap: stdout/stderr/logcat  │
└───────────────────────────────────┘
```

## Two planes

- **Control plane** — the Inspector MCP server + orchestrator. Distributed both as a local package (stdio) and a hosted service (streamable HTTP, for cloud agents). Owns all state and intelligence.
- **Execution plane(s)** — sandboxes where the app actually runs. Linux (E2B Desktop) covers web / Electron / Android. **iOS is a physically separate macOS plane** because the simulator cannot run on Linux (hard constraint). Both planes expose the same session interface; only the backend calls differ (`xdotool` vs `adb` vs `simctl`).

## Component map

| Component | Responsibility | Build/Buy | Detail |
|---|---|---|---|
| MCP tool layer | Expose tools to host agent | Build on SDK | [03](03-mcp-contract.md) |
| Session manager | Lifecycle, state machine, Tasks | Build | [03](03-mcp-contract.md) |
| Surface adapters ×4 (web/Electron/Android/iOS) | Implement `launch/is_ready/screenshot/input/logs` per surface | Build (core IP) | [04](04-core-loop.md) |
| Sandbox substrate | Virtual desktop + input/capture | **Buy** (E2B Desktop) | [02](#two-planes) |
| Element detector | Screenshot → Set-of-Mark | Buy/host (OmniParser) | [04](04-core-loop.md) |
| Action dispatcher | element-ID/coords → input event per surface | Build | [04](04-core-loop.md) |
| Detection engine | crashes/errors + visual anomalies | Build | [05](05-detection-and-feedback.md) |
| Finding store + trace | Structured findings + replay artifacts | Build | [05](05-detection-and-feedback.md), [06](06-data-schema.md) |
| Loop controller | caps, no-progress, confidence, PR-gate | Build | [05](05-detection-and-feedback.md) |
| Dashboard | View runs, replays, history | Build (later) | [07](07-dashboard.md) |

## Deployment

- **Control plane:** npm/pip package for local stdio use; hosted service for cloud agents and CI.
- **Linux execution plane:** E2B-managed sandboxes (or self-hosted Firecracker microVMs). Element detector co-located as a small service.
- **macOS/iOS plane:** pool of cloud Mac runners or Corellium behind the same session interface.
- **Concurrency:** one sandbox per session; warm pool + recycle for fast starts.
- **Storage:** session artifacts (action log, screenshots, findings, traces) written as structured JSON + a trace folder — see [06](06-data-schema.md). This makes the dashboard pure frontend over an existing format.
