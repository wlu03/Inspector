# Inspector — Deliverables

The full list of what's needed to take Inspector from "web M0 proven" to "multimodal,
shippable." Status: ✅ done · ◑ partial · ☐ todo · ⛔ blocked on external.

Task numbers reference the tracked backlog (see also the project's task list).

---

## 1. Core engine — ✅ done (web)
- ✅ MCP server (FastMCP): `launch_app / observe / act / verify / get_findings / stop`
- ✅ `Session` + `SessionManager` (state machine, lifecycle, sandbox-leak guards, atexit sweep)
- ✅ `SurfaceAdapter` interface
- ✅ Perception: OmniParser detector (Replicate + http backends) + Set-of-Mark renderer
- ✅ Action dispatcher + **verify-after-act**
- ✅ Detection: deterministic log/console findings (+ CDP console capture on web)
- ✅ Trace recorder + HTML/GIF replay
- ✅ Loop guardrails: iteration/wall-clock caps, no-progress hash, keep-alive heartbeat

## 2. Execution planes (the VMs)
- **Linux plane (E2B)** — ◑
  - ✅ E2B sandbox lifecycle (`inspector/sandbox.py`, `planes/linux.py`)
  - ☐ migrate web/Electron adapters onto `LinuxPlane` (currently use `E2BSandbox` directly)
  - ☐ optional self-hosted Firecracker/Cloud-Hypervisor backend
- **macOS plane (tart)** — ☐ scaffold only
  - ☐ `MacOSPlane.start/run_sync/run_bg/upload/screenshot/stop` over SSH (`planes/macos.py`)
  - ☐ `infra/macos-tart/setup.sh` live-tested on an Apple-silicon host
  - ⛔ iOS Simulator runtime install (~7GB) inside the VM
- **Android runtime (Redroid)** — ☐ scaffold only
  - ☐ `infra/android-redroid/setup-host.sh` + `docker-compose.yml` live-tested
  - ☐ `RedroidRuntime.start` (`planes/android.py`)
- **Corellium plane (alt iOS)** — ☐ optional (`planes/CorelliumPlane`, `infra/ios-corellium/`)

## 3. Surface adapters
- **web** — ✅ live (detect, crop, CDP console, click, verify-after-act)
- **electron** — ◑ launch + xdotool window detection wired; ☐ live-test on a real Electron app · **#8**
- **android** — ☐ skeleton → implement adb install/launch/screencap/input/logcat · **#9**
- **ios** — ☐ skeleton → implement simctl/idb over the macOS plane · **#10**

## 4. Sample apps (fixtures) — ✅ scaffolded, ☐ build/run in-plane
- ✅ `examples/sample-buggy-app` (web) — live-proven
- ✅ `examples/sample-buggy-electron` (Electron) — ☐ run in Linux plane
- ✅ `examples/sample-buggy-android` (Expo/RN) — ☐ build APK + run in Redroid
- ✅ `examples/sample-buggy-ios` (SwiftUI + xcodegen) — ☐ build + run in Simulator

## 5. Validation — the existential gate
- ☐ **#6** Validate the real agent loop in Claude Code (let a real model pilot it)
- ☐ **#7** Run on 2–3 real-world web apps (auth, routing, dense UIs)

## 6. Detection depth & actionable findings
- ☐ **#11** Enrich findings — file:line from stack traces, dedup, repro steps
- ☐ **#18** Visual-diff + layout-anomaly detection (catch visual bugs the log tap misses)
- ☐ **#19** axe-core accessibility checks (web/Electron)

## 7. Reliability (remaining review backlog)
- ☐ **#13** Pin crop geometry to the detection frame (full observe→act fix)
- ☐ **#14** Replay quality (letterbox, step-aligned captions, corrupt-frame safety)
- ☐ **#15** Reduce detector noise / tighter app crop
- ☐ **#16** Robust runtime error handling + session reaper + dead-sandbox detection
- ☐ **#17** DRAG support (destination params)

## 8. Cost / performance
- ☐ **#12** Self-host OmniParser (Modal/GPU) + result caching; trim per-step cost

## 9. Product surfaces
- ☐ **#20** Exploratory bug-finding (crash/invariant oracle)
- ☐ **#21** CI/autonomous mode + hosted dashboard (the monetization surface)
- ☐ **#22** Packaging & onboarding (PyPI, install/config docs)

## 10. Accounts / infra to provision
See [docs/12 — Accounts & Services](docs/12-accounts-and-services.md). Minimum to
go fully multimodal in VMs:
- ☐ E2B (Linux plane) · ☐ Replicate or self-hosted OmniParser
- ☐ Docker Hub + a Linux host with binder/ashmem (Android/Redroid)
- ☐ An Apple-silicon host + `tart` (iOS macOS VM) — **or** Corellium / cloud Mac

---

### Suggested order
1. **#6** (validate the loop with a real agent) — do before building more adapters.
2. **#8** Electron live (cheapest second surface, same plane).
3. **#11** actionable findings (makes autonomous fixing real).
4. **#9** Android (Redroid host), then **#10** iOS (macOS VM).
5. Reliability backlog (#13–17), cost (#12), then product (#20–22).
