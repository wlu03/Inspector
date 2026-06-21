# Inspector — Full Build Plan

> **Inspector** is an MCP server that lets a coding agent (Claude Code / Cursor) **see, operate, and test the app it just built** — across **web, Electron, Android, and iOS** — using **pure computer-use** (OmniParser Set-of-Mark grounding, not Playwright), all inside **VMs**, returning **reproducible findings** so the agent can fix bugs autonomously.

This is the authoritative, living build plan. Status markers: 🟢 built · 🟡 partial · 🔴 missing/stub. Priority P0–P3, effort S/M/L/XL. **★ = spec-mandated gap** (docs/03, docs/09) that the product promise depends on.

---

## 1. Architecture

```
Host agent (Claude Code / Cursor) ── MCP ──▶ Inspector server (FastMCP, stdio)
   = the "brain"                                 = eyes + hands
                                                     │
        ┌────────────────────────────────────────────┼─────────────────────────────┐
        │ SurfaceAdapter (web/electron/android/ios)   │  ExecutionPlane (the VM)     │
        │  launch · is_ready · screenshot · input ·   │   Linux/E2B  · macOS/tart    │
        │  logs · teardown                            │   Android/Redroid · iOS/sim  │
        └─────────────────────────────────────────────┴─────────────────────────────┘
                                                     │
   Perception: OmniParser V2 (Replicate or self-host) → elements → Set-of-Mark render
   Loop: observe → decide (driver or host agent) → act → judge → LoopGuard tripwires
   Output: trace (frames + actions.jsonl + logs.jsonl) → findings (file:line, repro) → replay (html+video)
```

**Two interaction modes:**
- **Host-driven (validated, high quality):** the host agent is the brain via the `run_test_session` plan loop (`set_plan` → `observe`/`act`/`verify` → `update_scenario` → `test_report`).
- **Autonomous (one-call):** `test_app` runs an embedded driver loop. Brain quality is the weak link (see Workstream ①).

---

## 2. Current status (built & proven)

- 🟢 **Web surface, end-to-end live-proven** — Chrome `--app` in E2B, tight app-window crop (panel killed), CDP console capture, coordinate translation. Caught the sample bug in a real Claude Code run.
- 🟢 **Pure-Python core** — session lifecycle, trace schema, SoM render, bbox normalization, driver/loop orchestration, plan tools, **11 MCP tools**.
- 🟢 **Autonomous `test_app`** — embedded driver + heuristic fallback + app-confinement (panel-kill, chrome-filter, position-dedup). *Wired and runs; brain quality pending.*
- 🟢 **Findings enrichment** — file:line extraction, dedup by signature, repro trails.
- 🟢 **43 passing unit tests** (all pure/mocked).

---

## 3. The five workstreams

1. **Autonomous-brain quality** — the existential weak link (default LLaVA is weak; Anthropic key plumbed-but-unused; no per-step verification).
2. **Cost / leak risk** — the only money-bleeding gaps (no reaper, no concurrency cap, no spend tripwire, host token cost).
3. **Surface expansion** — Electron (one refactor away) → Android (Redroid) → iOS (macOS/tart).
4. **Eval** — no objective "does it work?" score; 6-bug fixtures exist but no scorer reads them.
5. **Productization** — README/PyPI/CI/dashboard/auth.

Plus four **spec gaps** the adversarial review elevated to P1: async launch, determinism, host token-cost mode, dev-server config.

---

## 4. Build list (grouped, prioritized)

### ① Autonomous brain
- `[P0·L·🔴]` Anthropic computer-use / SoM-grounded Claude driver as the **default brain** (key plumbed but unused).
- `[P1·M·🔴]` Per-step expectation verification (compare post-act state to `Decision.expectation`).
- `[P1·M·🟡]` Perceptual/structural no-progress diff (exact-byte hash never fires on live apps).
- `[P1·S·🟡]` Decouple LoopGuard from `act` so `exhausted()` is meaningful.
- `[P1·M·🟢]` Broaden FallbackDriver beyond literal `"wait"` (confident-wrong clicks, exception-waits).
- `[P2·S·🟡]` Driver retry/backoff + timeout + token/latency telemetry.
- `[P2·M·🟡]` Harden `_confine` to geometric viewport bounds (denylist is brittle); apply at act-time.
- `[P2·M·🟡]` Require evidence for VLM-judged bugs; tighten bare `\berror\b` matcher.
- `[P2·S·🟡]` Cost/token budget tripwire; make `no_progress_limit` configurable.

### ② Cost / leak risk
- `[P0·M·🔴]` Background **session reaper** (idle/wall-clock TTL + last-touched).
- `[P1·M·🟡]` Concurrency lock on `SessionManager.sessions` + per-session serialization + max-sandbox cap.
- `[P1·M·🔴] ★` Host **token-cost mode** — return SoM text list by default, gate full PNG behind a flag + per-session image budget.
- `[P1·M·🔴]` Per-detection latency + Replicate cost instrumentation into trace.

### ③ Surfaces & planes
**Electron** (one refactor from working):
- `[P0·M·🟡]` Hoist crop + coord-translation into shared `DesktopAdapter`.
- `[P0·M·🟡]` Parameterize CDP console listener (9222→9223) + connect Electron renderer console.
- `[P0·S·🟡]` Gate Electron readiness on CDP page-target + kill XFCE panel.
- `[P0·M·🔴]` Live-test Electron vs `sample-buggy-electron` (6 bugs).

**Android** (all stubs):
- `[P1·M·🟡]` Validate Redroid-inside-E2B bootability vs self-managed ARM64 host (binder/ashmem).
- `[P1·L·🔴]` `RedroidRuntime` lifecycle (docker run + adb connect + wait-for-device).
- `[P1·L·🔴]` `AndroidAdapter` (adb install/`am start`/screencap/input/logcat/`wm size`).

**iOS** (stubs, needs macOS plane first):
- `[P2·L·🔴]` `MacOSPlane` SSH transport (tart+ssh).
- `[P2·S·🔴]` `INSPECTOR_MACOS_HOST` + SSH settings in `config.from_env`.
- `[P2·L·🔴]` `IOSAdapter` (simctl + idb).
- `[P3·L·🔴]` `CorelliumPlane` (optional alternative).

**Plane plumbing:**
- `[P1·M·🟡]` Wire the `ExecutionPlane` abstraction in (dead code today).
- `[P1·S·🔴]` E2B custom template with Chrome baked in (kills 30–60s install).
- `[P2·S·🔴]` Real teardown for macOS/Redroid/mobile adapters (bare `pass` → leaks).
- `[P2·M·🟡] ★` Validate OmniParser grounding on RN/SwiftUI frames before adb/idb.

### ④ Perception & detector
- `[P0·S·🟡]` Lock `detector.py` to confirmed OmniParser contract; remove `[VERIFY]`.
- `[P1·S·🟡]` Reconcile `use_paddleocr` mismatch (probe vs production).
- `[P2·M·🟡]` Deploy/document self-host OmniParser GPU server + caching.
- `[P2·M·🔴]` Detector noise control (threshold, IoU dedup, max-element cap).
- `[P3·M·🔴] ★` Grounding-model upgrade seam (UI-TARS / coords fallback) for canvas/WebGL.
- `[P3·M·🟡]` Implement-or-remove the advertised `"local"` backend.

### ⑤ MCP contract & orchestration
- `[P1·M·🔴] ★` Async `launch_app` via Tasks primitive (cold boot 30–120s blocks the call).
- `[P2·M·🔴] ★` `report_issue` tool (host agent can't file a finding it sees).
- `[P1·S·🟡]` Fix `verify()` (always `passed=False` once any finding exists; returns no screenshot).
- `[P2·M·🟡]` Implement DRAG (`to_target_id`/`to_coords`).
- `[P2·L·🔴]` Resumability: `list_sessions` + rehydrate-from-trace + wire `Run`/`save_run`.
- `[P2·S·🟡]` Friendly error-dict for bad enum/session_id at the tool boundary.

### Determinism, findings, replay, trace
- `[P1·M·🔴] ★` Determinism controls (seed / frozen clock / TZ / network HAR) — HARD constraint for "reproducible findings".
- `[P2·M·🔴] ★` Fix-loop closure (re-verify after edit; `Finding.status` open→fixed→verified).
- `[P1·M·🟡]` Crash-safe trace writes (atomic tmp+rename, persist frame counter, fsync).
- `[P1·S·🔴]` Wire `Run` + `save_run` + `ended_at`/`task_id` at session end.
- `[P2·S·🔴] ★` Surface live E2B stream URL (`stream.get_url`, zero callers).
- `[P2·M·🟡]` Richer replay (captions + before/after pairing + click-target overlay).
- `[P2·L·🔴]` Visual-diff / layout / crash-screen detector.
- `[P3·M·🔴]` axe-core a11y; source-map resolution.

### Real-app launch reality
- `[P1·M·🔴] ★` Dev-server config (`.env` stripped on upload → false bugs); sandbox-safe env injection + companion-backend story.
- `[P2·M·🟡] ★` Composed multi-signal readiness (SSR/SPA/Vite, slow first build, error-overlay-as-ready).

### Eval
- `[P0·L·🔴]` Bug-scoring harness (load `bugs.json` → run → match by signature+screen → precision/recall).
- `[P1·M·🔴]` Credential-gated live pytest tier (`@pytest.mark.live`).
- `[P1·L·🟡]` Build + live-run electron/android/ios fixtures.
- `[P2·S·🔴]` Fixture-drift guard + per-surface graded validation docs.

### Security (app under test is untrusted)
- `[P2·M·🔴] ★` Untrusted-app threat model (E2B egress / Redroid `--privileged`).
- `[P2·M·🔴]` Auth/authz + repo_path allowlist for HTTP/SSE.
- `[P2·M·🟡]` Secret/PII redaction; repo_path traversal guard.

### Productization
- `[P1·S·🟡]` Fix stale README ("Planning. No code yet.").
- `[P2·M·🔴]` Structured logging (replace silent `except: pass`).
- `[P2·M·🔴]` PyPI + CI + portable `.mcp.json`.
- `[P2·L·🔴]` CI/autonomous runner (scheduler + exit-code-on-findings + PR bot).
- `[P3·XL·🔴]` Trace-backed dashboard.
- `[P3·S·🔴] ★` Pre-build build-vs-buy validation (Swarm / E2B MCP / ScreenPipe).

---

## 5. Critical path (build order)

1. **Lock the OmniParser contract** (P0·S) — de-risk the detector the whole loop rides on.
2. **Anthropic brain** (P0·L) — real testing instead of breadth-first clicking. *(needs ANTHROPIC_API_KEY)*
3. **Session reaper** (P0·M) — stop the only money-bleeding gap.
4. **Bug-scoring harness** (P0·L) — objective "does it work?" gate.
5. **Electron** (P0 ×4) — prove surface #2.
6. **Elevated spec gaps in parallel** (P1·★): async launch · determinism · host token-cost · dev-server `.env`.
7. **Android** (validate bootability → RedroidRuntime → AndroidAdapter), then **iOS** (MacOSPlane → IOSAdapter), each **mobile-grounding-validated first**.
8. **Productization** (PyPI / CI / dashboard) last.

---

## 6. Implementation log

_(append as parts land)_
- ✅ Web M0 live loop; plan-driven host loop; findings enrichment; autonomous `test_app` + confinement.
- ✅ **OmniParser contract locked** — probed live: `{elements, img}`, newline `"icon N: {single-quoted dict}"`, bbox **ratios (0..1)**; `[VERIFY]` removed; regression test.
- ✅ **Session reaper + thread-safe SessionManager** — RLock around the sessions dict; daemon reaper tears down sessions idle > `session_idle_ttl_s` or older than `sandbox_timeout_s`. Stops billed-sandbox leaks.
- ✅ **Anthropic brain driver** — `AnthropicDriver` reuses the same prompt+parser; `INSPECTOR_DRIVER=anthropic` (or `auto` → Claude-if-key-else-Replicate). Default stays `replicate`. *Needs `ANTHROPIC_API_KEY` to use.*
- ✅ **`verify()` fixed** — error signal scoped to findings-since-last-verify (no more permanent `passed=False`); now returns the screenshot.
- ✅ **`report_issue` tool** — host agent can file structured findings it judged from the screenshot (host-as-brain).
- ✅ **Host token-cost mode** — `observe`/`act` take `include_image`; `max_images_per_session` cap → text element list only past the budget.
- ✅ **Bug-scoring eval harness** — `inspector/eval.py` (pure `match_findings` → precision/recall/F1) + `scripts/eval.py` CLI; scores findings vs each fixture's `bugs.json` signatures. The objective "does it work?" gate.
- ✅ **Async launch** — `launch_app(wait=false)` returns immediately + `launch_status(session_id)` polls to READY; avoids host tool-call timeouts on cold boot.
- ✅ **Fix-loop closure** — `report_issue` (host-filed findings) + `update_finding_status` (open→fixed→verified→dismissed); re-verify by re-running. MCP surface now 13 tools.
- ✅ **Adversarial framing + attack catalog** — `inspector/adversarial.py`: per-feature "try to break it" catalog (forms/modals/nav/empty-states/a11y/robustness/responsive) + `EDGE_INPUTS` (empty/XSS/SQL/overflow/special/unicode/negative). Brain prompt (`_SYSTEM` + `build_decision_prompt`) flipped from "exercise" to "stress/break"; `HeuristicDriver` now pushes a *distinct* edge payload into each field instead of one benign string. Ports ui-test's adversarial mindset.
- ✅ **Deterministic DOM audit (evidence tier)** — `adapters/cdp.py:audit_dom` injects axe-core over CDP and reads WCAG violations + broken images (naturalWidth=0) + unlabeled inputs; `audit.py:audit_to_findings` (pure) maps them to severity-tagged Findings; `SurfaceAdapter.audit_dom` hook (web wired, native no-ops); `Session.audit()` ingests with dedup; new `audit_dom` MCP tool (14 tools) + auto-run at the end of `test_app`. Recovers ui-test's strongest `browse eval` evidence tier.
- ✅ **Three-round adversarial planning** — `run_test_session` prompt now drives Round 1 functional → Round 2 adversarial → Round 3 coverage (a11y/keyboard/404/mobile), embeds the catalog, and tells the agent to prefer adversarial moves + call `audit_dom`.
- ✅ Tests: `tests/test_adversarial.py` + `tests/test_audit.py` (8 new; suite 86 passing, all pure/mocked).
- ✅ **Electron adapter finished + live-validated (#8)** — completed the adapter (Node install, electron native deps, headless launch + `DISPLAY=:0`, CDP-gated readiness on 9223, panel-kill, window crop, **renderer-console capture on 9223**). Live probe: launches `ready=true`, crops cleanly to the window, detects controls by label, and a real listed bug (**BUG-06** `missing a11y label on primary action`) flowed renderer `console.error` → log tap → finding with repro `["type 'Alice'", "click element #4 (Save)"]`. Surface #2 proven. Autonomous eval recall is brain-limited (LLaVA), not adapter-limited.
- ✅ **Cross-surface type-focus fix** — `DesktopAdapter.input` clicks the target to focus before typing; typing without focus dropped keystrokes so forms never filled and form-dependent bugs never fired. Affects web + electron. (Surfaced by the Electron live test.)
- ⏳ Next: per-step before/after structured assertion (STEP_PASS/FAIL) · diff-driven `test_changes` (git diff → screens) · viewport/404/keyboard primitives · ui-test-style HTML report · broaden FallbackDriver (catch empty-type/bad actions) · determinism (#28) · dev-server `.env` (#29) · Android/iOS planes.
