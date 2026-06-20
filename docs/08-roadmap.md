# 08 — Build Plan

Inspector is **multimodal from day one**: a surface-agnostic core plus one `SurfaceAdapter` per surface. You build the core once; each of **web, Electron, Android, iOS** plugs in without touching it. This doc is the full development inventory; for the **ordered, concrete steps + exact APIs/commands** to build each item, see [11 — Implementation Steps](11-implementation-steps.md).

Effort scale: **S** = days · **M** = 1–2 wks · **L** = ~1 mo · **XL** = multi-month / research-hard.

## The model

```
                ┌──────────────── shared core (built once) ─────────────────┐
                │ MCP tools · session mgr · perception (detect→SoM) ·         │
                │ action dispatcher · detection · trace · loop · guardrails   │
                └───────────────────────────┬───────────────────────────────┘
                                            │ SurfaceAdapter interface
        ┌──────────────┬───────────────────┼───────────────────┬──────────────┐
     web adapter   electron adapter    android adapter      ios adapter
   (Linux plane)   (Linux plane)       (Redroid)            (macOS plane)
```

Each adapter implements: `launch · is_ready · screenshot · input · logs · teardown`.

---

## Section 1 — Shared core (surface-agnostic, build once)

- [ ] **MCP server** (FastMCP) — `launch_app`, `observe`, `act`, `verify`, `get_findings`, `stop` · **M**
- [ ] **Session manager** — session object, state machine, long-running Tasks pattern · **M**
- [ ] **`SurfaceAdapter` interface** — the abstraction all four surfaces implement · **S**
- [ ] **Perception: element detector** — screenshot → OmniParser → element list · **S–M**
- [ ] **Perception: Set-of-Mark renderer** — numbered boxes → annotated PNG · **S**
- [ ] **Action dispatcher** — `{target_id|coords}` → active adapter's `input()` + **verify-after-act** · **M**
- [ ] **Detection engine** — shared log-tap parser → deterministic crash/error findings · **S–M**
- [ ] **Finding synthesis** — structured JSON findings + confidence · **M**
- [ ] **Trace recorder** — `actions.jsonl` + `frames/` + `logs.jsonl` + findings (doc 06 schema) · **M**
- [ ] **Loop controller + guardrails** — iteration/cost caps, no-progress hash, PR-not-merge · **M**
- [ ] **Data models** — Session / Element / Action / Finding / Run (pydantic) · **S**
- [ ] **Config + CLI** — `.mcp.json` wiring, surface selection · **S**

## Section 2 — Surface adapters (the multimodal part — 4 implementations)

### 2a. Web adapter · **S–M** · Linux plane
- [ ] Launch: detect framework + dev command (`package.json` → Vite/Next/CRA)
- [ ] Runtime: browser in E2B Desktop
- [ ] Readiness: `wait-on` HTTP 2xx + `detect-port`
- [ ] Capture/input: scrot + xdotool
- [ ] Log tap: dev-server stdout/stderr (+ optional browser console)

### 2b. Electron adapter · **M** · Linux plane
- [ ] Launch: detect `electron` in deps / `electron .`
- [ ] Runtime: E2B Desktop + Xvfb display, runs natively on XFCE
- [ ] Readiness: window mapped (`xdotool search --name`)
- [ ] Capture/input: scrot + xdotool
- [ ] Log tap: main + renderer stdout/stderr

### 2c. Android adapter · **M–L** · Redroid
- [ ] Launch: detect Expo/RN/native (`app.json`, `gradlew`); build/install APK
- [ ] Runtime: Redroid container (no-KVM) on ARM64
- [ ] Readiness: `adb wait-for-device` + focused activity
- [ ] Capture/input: `adb screencap` + `adb input` / UiAutomator gestures
- [ ] Log tap: logcat

### 2d. iOS adapter · **L–XL** · macOS plane ⚠️
- [ ] Launch: detect Expo/RN/native (Xcode project); build for simulator
- [ ] Runtime: iOS Simulator on macOS host (cloud Mac / Corellium) — *cannot run on Linux*
- [ ] Readiness: `simctl` boot + app-launched state
- [ ] Capture/input: `simctl io screenshot` / idb tap+type
- [ ] Log tap: `idevicesyslog` / `simctl spawn log`

## Section 3 — Runtime / plane infrastructure

- [ ] **Linux execution plane** — E2B Desktop provisioning, pooling, teardown (web/Electron/Android) · **M**
- [ ] **macOS execution plane** — Mac runner / Corellium pool behind the same session interface (iOS) · **L**
- [ ] **Sandbox lifecycle** — one sandbox per session, warm pool, recycle · **M**

## Section 4 — Detection (full)

- [ ] Deterministic: crash/exception/error (all surfaces, via log tap) · **S**
- [ ] Accessibility: axe-core (web/Electron) · **S**
- [ ] Visual: pixel-diff → host-VLM judgment (confidence-gated) · **M**
- [ ] Layout anomalies: element-bbox geometry · **M**
- [ ] Exploratory bug-finding scoped to crash/invariant oracle (research-hard) · **XL**

## Section 5 — Dashboard (schema designed now, built later)

- [ ] Local viewer — run list + replay timeline over the trace format · **M**
- [ ] Hosted dashboard — history, trends, sign-off, team (the paid layer) · **L**

---

## Milestones

| # | Milestone | Definition of done |
|---|---|---|
| **M0** | **Core loop proven** | Shared core + `SurfaceAdapter` + the first runtime (web) close one directed-verification loop unattended (see acceptance test below) |
| **M1** | **Linux plane complete** | Web **and** Electron adapters production-usable; guardrails + trace on disk |
| **M2** | **Android online** | Redroid plane + Android adapter; same loop on a mobile surface |
| **M3** | **iOS online** | macOS plane + iOS adapter; all four surfaces live |
| **M4** | **Detection depth** | Visual + a11y + scoped exploratory; local replay dashboard |
| **M5** | **Productize** | Hosted dashboard, CI integration, paid tier |

### M0 acceptance test
> In Claude Code, against a sample web app with a silently-failing Save button:
> launch → observe (numbered screenshot) → act click #7 → `changed:false` + log error → agent reports a reproducible finding → fixes code → re-verify `changed:true` → trace written → ends in a PR, not an auto-merge.

If that runs unattended once, the core thesis holds and every adapter is incremental.

## Bring-up order (by infra readiness, not product scope)

All four surfaces are **in scope as the product**. The *order you stand up runtimes* is driven by infra cost, not by deferring surfaces:

1. **Web** — cheapest plane; proves the core (M0).
2. **Electron** — same Linux plane, near-free (M1).
3. **Android** — adds Redroid (M2).
4. **iOS** — separate macOS plane, ~3–4× infra cost (M3).

Write the core + all four adapter interfaces from the start so the architecture is multimodal on day one; bring each runtime online as its plane is ready.

## Component effort summary

| Component | Effort | Notes |
|---|---|---|
| Shared core (Section 1) | M–L total | Built once, surface-agnostic |
| Web adapter | S–M | Linux plane |
| Electron adapter | M | Linux plane |
| Android adapter | M–L | Redroid |
| **iOS adapter** | **L–XL** | macOS hard wall + cost |
| Linux plane | M | E2B Desktop |
| macOS plane | L | Mac/Corellium pool |
| Detection (deterministic) | S | Log tap, axe-core |
| Detection (visual/exploratory) | M / XL | host VLM / research-hard |
| Trace + loop + guardrails | M | |
| Local dashboard | M | View over trace format |
| Hosted dashboard | L | Storage, auth, multi-user |
