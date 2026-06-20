# 08 — Roadmap

Effort scale: **S** = days · **M** = 1–2 wks · **L** = ~1 mo · **XL** = multi-month / research-hard.

## Phases

### v0 — Prove the core loop (web + Electron)
**Goal:** show grounding-by-ID + host-decides + verify-after-act actually closes an autonomous directed-verification loop.
- E2B Desktop sandbox + launch a Vite/Next app + `wait-on` readiness.
- screenshot → OmniParser Set-of-Mark → return to host → `act` by ID → verify-after-act.
- Detection v1: log tap → deterministic crash/error findings → structured report.
- MCP packaging: tool contract + Tasks pattern + session state machine. Plug into Claude Code; run one real directed-verification loop end to end.
- Guardrails: caps, no-progress, PR-not-merge. Write trace artifacts to disk ([06](06-data-schema.md)).
- Add Electron (same Linux plane, near-free).

**Exit criteria:** from Claude Code, "verify this change" launches the app, exercises the changed flow, catches an introduced bug, returns a reproducible finding, and the agent fixes + re-verifies — unattended, ending in a PR.

### v1 — Broaden + harden
- Add **Android** (Redroid; swap input backend to adb/logcat).
- Better grounding + verify-retry robustness; UI-TARS fallback option.
- Full guardrail stack + confidence gating for visual findings.
- Replay traces + minimal **local dashboard** (run list + replay timeline, [07](07-dashboard.md)).
- Visual detection: pixel-diff → host-VLM judgment.

**Exit criteria:** reliable across web/Electron/Android; a human can audit any run via replay; visual regressions caught with acceptable false-positive rate.

### v2 — Hard frontier + commercialization
- **iOS** (separate macOS plane: cloud Mac / Corellium; simctl/idb backend).
- **Exploratory** bug-finding scoped to crash/invariant oracle.
- **Hosted dashboard** with history, trends, team sharing, sign-off — the monetization surface; lead with it for CI/autonomous runs.
- CI integration (run on PR, gate merges).

**Exit criteria:** all four surfaces; autonomous/CI runs with a trustworthy review surface; a paid tier.

## Build sequence (concrete order)

1. Spike core loop, web only (E2B + readiness + SoM + act-by-ID + verify-after-act).
2. Detection v1 (log tap → deterministic findings → report).
3. MCP packaging (tool contract, Tasks, session state machine) → real loop in Claude Code.
4. Guardrails + trace artifacts to disk.
5. Electron (same plane).
6. Android (Redroid; adb backend).
7. Local dashboard (replay timeline).
8. iOS (macOS plane).
9. Visual + exploratory detection.
10. Hosted dashboard + CI + monetization.

## Component effort summary

| Component | Effort | Notes |
|---|---|---|
| Sandbox substrate | S (adopt) | Buy E2B Desktop |
| Launch + readiness detection | M | Core IP; fuzzy per framework |
| Element detector → SoM | S–M | Adopt OmniParser |
| Action dispatcher (per surface) | M | xdotool/adb/simctl |
| Detection (deterministic) | S | Log tap, axe-core |
| Detection (visual) | M | pixel-diff + host VLM |
| Feedback synthesis + repro | M | JSON findings + action-log replay |
| Loop controller + guardrails | M | Caps, no-progress, PR-gate |
| MCP server | M | SDK + stateful sessions |
| Android plane | M–L | Redroid |
| **iOS plane** | **L–XL** | macOS hard wall + cost |
| Local dashboard | M | View over trace format |
| Hosted dashboard | L | Storage, auth, multi-user |
