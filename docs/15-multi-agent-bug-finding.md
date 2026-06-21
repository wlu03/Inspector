# 15 — Multi-agent, region-decomposed bug finding ("Cartographer")

**Status:** design + concrete plan (not yet built). Supersedes the single-brain `test_app`
loop for *quality* runs; `test_app` stays as the cheap exploratory path.

## 0. Why

Live evals exposed three failure modes of the single autopilot brain
(`autopilot.py` → `driver.decide`):

| Observed failure | Evidence | Root cause |
|---|---|---|
| **Wanders** — undirected, `no_progress` thrash | macOS run did input-fuzzing, never tested the counter | one brain, one "find bugs" goal, LLM picks the action |
| **Over-flags** — reports its own injected payloads | macOS **0/3, 10 false-positives** (all self-typed XSS/`AAAA…`) | judge asked "is this broken?" on a single frame, no provenance check |
| **Misses silent logic bugs** | Flutter **1/3** (missed `Plus += 2`, `Reset = 1`) | single-screenshot vision vote can't compare two states of one element |

These map to three sub-problems with strong prior art (the citations the user supplied):
**explore** without wandering, **detect** silent/sequence bugs, **gate** candidates so
self-inflicted findings die. The design fuses a region-decomposition spine
(each agent owns one part of the UI) with those three fixes.

## 1. The architecture — four orthogonal layers

```
        ┌─────────────────────────────────────────────────────────────┐
  build │ host (Claude Code) builds a feature → "inspect it, hand me fixes"
        └─────────────────────────────────────────────────────────────┘
                                   │  test_feature(repo, diff/feature)
  ┌────────────────────────────────▼─────────────────────────────────┐
  │ 1. WHERE   MAPPER  → bounded Regions; one REGION-AGENT per region │  region-decomposition
  │ 2. EXPLORE per-region state-graph + coverage-targeted selection   │  AutoDroid / Fastbot2
  │            + CONSTRAINED action output (no LLM in the choice)      │
  │ 3. DETECT  layered oracles: deterministic lens-oracle             │  Genie / Odin / Trident
  │            → differential/metamorphic → sequence-aware MLLM        │
  │ 4. GATE    VERIFIER: infer-expected-first → replay → 2-of-2        │  Trident / Odin
  └────────────────────────────────┬─────────────────────────────────┘
                                    ▼
                 ranked FixItem list  →  host applies suggested_fix  →  re-run to confirm `cleared`
```

Each layer kills one observed failure: **EXPLORE** kills wandering, **DETECT** kills missed
logic bugs, **GATE** kills over-flagging, **WHERE** keeps each agent focused on one part.

## 2. Five roles (the Cartographer spine: MAP → ASSIGN → INVESTIGATE → VERIFY → MERGE)

1. **Mapper** (`inspector/mapper.py`, **deterministic, no LLM**) — `segment(elements, screenshot) → list[Region]`.
   `Region{region_id, title, bbox (union of member bboxes, 0..1), member_element_ids, role_class ∈ {nav,form,list,panel,header,toolbar,modal}}`.
   `region_id` = stable hash of `(role_class + sorted normalized labels + rounded bbox)` — stable
   across observations (de-dup key) **and across builds** (diff-scoping).
2. **Coordinator** (`inspector/orchestrator.py`) — clones the `test_app` launch envelope, observes,
   maps, then per region installs a fresh small `LoopGuard` and spawns **one** region-agent.
   v1 sequential (the single CDP/idb transport is serialized by `session._capture_lock`); N-session
   parallel via `SessionManager.create` later.
3. **Region-agent** (`inspector/region_agent.py`) — a `HypothesisDriver` implementing the existing
   `decide(som, elements, goal, history, logs) → Decision` interface, so it drops into
   `run_autopilot` unchanged. Runs `propose_hypotheses` → per-hypothesis `NAVIGATE → CAPTURE →
   TRIGGER → MEASURE` → deterministic oracle. Emits `Decision.bug` **only** on a measured oracle
   violation or a real `scan_logs` signature.
4. **Verifier** (`inspector/verifier.py`) — independent replay of the candidate's minimal trigger in
   a *fresh* session, recompute the same oracle, **2-of-2** to confirm; + self-payload guard + semantic gate.
5. **Merger / fix-writer** (`inspector/merger.py`) — de-dup (`finding_signature` + cross-region
   semantic), compose one `suggested_fix` per survivor from its `source_ref`.

**Free wins from existing code** (no new mechanism needed):
- **Confinement is structural.** A region-agent's `decide()` only ever sees
  `region_confine(elements, region)` (a 5-line clone of `autopilot._confine`). `parse_decision`
  (driver.py:119) **already nulls any `target_id` not in the supplied list** → an out-of-region
  click becomes a no-op. The agent *physically cannot* leave its bbox.
- **De-dup is automatic.** All agents write to one `session.trace`; `session._ingest_findings`
  already de-dups by `detection.finding_signature`.
- **Replay/markers free.** Findings flow through `save_finding` + carry `bbox` → the clickable
  replay (docs §replay) lights up with no extra work.

## 3. Layer 2 — EXPLORE: state-graph + coverage-targeted selection + constrained actions

> *Fixes wandering. Prior art: AutoDroid [2308.15272], LLM-Explorer, Fastbot2 [ASE'22].*

The region-agent's `NAVIGATE→CAPTURE→TRIGGER→MEASURE` protocol is already directed for the
*modeled* lenses. The state-graph substrate handles the parts that still need exploration
(reaching a screen, enumerating list/nav states) and replaces the LLM in the *action choice*:

- **UI Transition Graph** (`inspector/explore/state_graph.py`): nodes = abstracted screens, edges
  = actions. **De-dup states by their a11y/DOM signature** (reuse the `rendered_elements()` label
  set + route as the screen fingerprint the NAVIGATION lens already builds). [AutoDroid / LLM-Explorer]
- **Coverage-targeted selection** (`inspector/explore/selector.py`): pick the action maximizing
  expected gain into *uncovered* states — softmax over a transition model + an N-step Sarsa Q-table.
  **No LLM in the choice** — this is the concrete replacement for the brain's near-random taps. [Fastbot2]
- **Constrained action output**: `parse_decision` already drops invalid ids; tighten the
  `AnthropicDriver` so the model can *only* emit `{valid element id, action}` — structurally
  eliminates `type ""` / `tap "Q"` (AutoDroid reports 90.9% action accuracy from this). [AutoDroid]
- **LLM only for** (a) merging equivalent states into the graph and (b) **content-aware text input**
  (types a real `"Alice"`, not `""`). Everything else is the deterministic selector.

The Cartographer region-protocols *are* a degenerate, fully-scripted path through this graph; the
selector is the fallback when a lens needs to reach a state the script doesn't name.

## 4. Layer 3 — DETECT: a layered, sequence-aware oracle stack

> *Fixes missed silent bugs. Prior art: Genie [OOPSLA'21], Odin, Trident [2407.03037].
> "No single oracle is trustworthy" — Odin ~67% FP, LLM-as-oracle 49% detect [2407.19053].*

Three tiers, cheapest/most-precise first; a candidate needs only one tier to fire, but the
VERIFIER (Layer 4) must independently re-confirm:

**Tier A — deterministic lens oracles** (precise, zero-FP, per modeled class). The 7 lenses, each a
hypothesis → protocol → **assertion on the app's own observable state** (never on injected input):

| Lens | Oracle (assertion) | Catches |
|---|---|---|
| **LOGIC_ARITHMETIC** | `COUNTER_DELTA: (after−before)==expected`; `RESET_TO: shown==init-literal` | Flutter `Plus+=2`, `Reset=1` |
| **STATE_SYNC / CONTROL_VS_STATE** | `bug iff label-changed XOR checked-changed` (compares control to itself) | Flutter/Electron toggle desync |
| **PERSISTENCE / CROSS-SCREEN** | `FIELD_PERSISTS: re-read == benign sentinel` | stale/blank cross-screen value |
| **NAVIGATION / BACK-STACK** | `SCREEN_FINGERPRINT: dest==expected, back==prior` | reset-routes-wrong, dead routes |
| **INPUT_VALIDATION (saboteur)** | bug **only** if invalid input *accepted* or crash — **never** "I see my payload" | validation bypass |
| **IDEMPOTENCY / ASYNC / EMPTY** | `COUNT_STABLE`, `ASYNC_SETTLES`, `EMPTY_RENDERS` | double-submit, hung spinner, blank empty-state |
| **ELEMENT_RENDERS / A11Y** | reuse `check_expectations` + `axe-core` serious/critical | declared-but-not-rendered, WCAG |

**Tier B — differential / metamorphic** (spec-free; `inspector/oracles/differential.py`). Catches
data-loss / wrong-display classes the lens oracles don't model — *the explicit motivation of the
Genie/Odin line.* Combine both, they catch different bugs (11/28 of Odin's were invisible to Genie):
- **Genie independent-view fuzzing**: equivalent independent paths to the same state must render the
  same content. [Genie]
- **Odin may-belief minority-cluster**: across many similar states, the *minority* rendering is the
  anomaly. [Odin]

**Tier C — sequence-aware MLLM** (`inspector/oracles/sequence_oracle.py`). The catch-all for the
unmodeled: reason over a **sequence of screenshots**, not one frame — because "value didn't persist"
/ "wrong screen after nav" only reveals *across transitions*. Trident hits 50–72% precision and is
**the single most relevant oracle for our iOS a11y-state bugs.** [Trident] Always followed by Layer 4.

## 5. Layer 4 — GATE: candidates, not findings

> *Fixes over-flagging. Prior art: Trident [2407.03037], Odin.*

A region-agent emits **candidates**; only the VERIFIER produces findings:

1. **Infer-oracle-first CoT** — the model must state the *expected* behavior **before** judging the
   actual (in `propose_hypotheses` and the Tier-C oracle). Trident credits this for reduced
   hallucination; we currently ask "is this broken?" directly — the worst form. [Trident]
2. **Self-payload guard** — auto-dismiss any candidate whose `actual` merely echoes an
   `adversarial.EDGE_INPUTS` value the agent itself typed. (This alone kills the macOS 10 FPs.)
3. **Replay confirmation** — re-run the minimal trigger in a *fresh* session and recompute the same
   oracle; promote only on **2-of-2** agreement. Odin found 21% of its FPs were unstable replay. [Odin]
4. **Decoupled judging** — the agent that *produced* a payload is never the agent that *confirms*
   it; the verifier must reproduce a measured failure from a clean launch.
5. **Semantic gate** — `eval._semantic_mapping` lifted almost verbatim rules
   `confirmed | self_inflicted | expected | vague`.

## 6. Output contract — the fix list back to the host

`test_feature` returns a ranked list of `FixItem`s (each reuses `Finding` fields + a `suggested_fix`,
so it serializes through `save_finding` and scores in `eval`):

```json
{ "scope": "diff|full", "regions_investigated": N, "confirmed": M, "cleared": K, "unreachable": U,
  "fixes": [ {
    "region": {"region_id":"rgn_a1b2","title":"Counter panel","bbox":[0.1,0.3,0.9,0.6]},
    "issue": "Plus increments the counter by 2 instead of 1",
    "evidence": { "before":{"frame_ref":"frame_0007.png","value":"0"},
                  "after":{"frame_ref":"frame_0008.png","value":"2"},
                  "a11y_diff":"count: 0 -> 2 (expected 0 -> 1)",
                  "oracle":"COUNTER_DELTA observed=2 expected=1",
                  "replay_ref":"replay.html#step=8",
                  "verified_by":"independent replay reproduced delta=2 from clean launch" },
    "suggested_fix": "lib/counter.dart:42 — change `_count += 2` to `_count += 1`",
    "source_ref": "lib/counter.dart:42", "severity":"high", "confidence":"high"
  } ],
  "replay": "<replay.html>", "dashboard_url": "..." }
```

`cleared` (oracle *passed* — a regression signal) and `unreachable` (region never reached — a nav
gap, not silently dropped) are **first-class** so the host knows exactly what was checked.

## 7. Diff-aware flow — "I built X, find its bugs"

`inspector/diff_scan.py`: host calls `test_feature(repo, feature="…", diff=<git diff>)` (or the
server runs `git diff HEAD~1` itself). Then:
1. `parse_diff` → added line ranges per file.
2. `extract_expected_in_diff` → re-run `source_scan` extractors, keep only `ExpectedElements` whose
   `source_ref` line falls in a changed hunk → the precise set of changed controls.
3. Bind changed elements → live regions by normalized label; a region is **CHANGED** if it contains
   ≥1; spawn agents **only** there.
4. **Lens routing per hunk** (regex/AST): `count +=`/`+2` → LOGIC_ARITHMETIC; `Switch/onChange/aria-checked`
   → STATE_SYNC; `navigate/router` → NAVIGATION; `required/type=email/maxLength` → INPUT_VALIDATION;
   `fetch/await/useEffect` → ASYNC; `.map(/length===0` → EMPTY_STATE. A region runs only the lenses
   its diff warrants.
5. **Gate** findings to `suspected_area ∩ changed_paths` — surfaces bugs in exactly what shipped.

Graceful degradation: NL feature only → coarse filename match + feature-derived hypotheses; nothing
binds → full sweep with the feature as a FOCUS hint. Always returns `{scope, reason}`.

## 8. Codebase integration (smallest diff)

**New:** `mapper.py`, `region_agent.py`, `orchestrator.py`, `verifier.py`, `merger.py`,
`diff_scan.py`, `explore/state_graph.py`, `explore/selector.py`, `oracles/differential.py`,
`oracles/sequence_oracle.py`.
**Edit (additive):**
- `driver.py` — `AnthropicDriver.propose_hypotheses(region_elements, region_source_facts)` (mirrors
  `judge_missing_element`; same `_run_model`/`_extract_json_object`); tighten constrained action output.
- `adapters/base.py` — `control_state(element_id) → {role,value,checked,expanded,selected,name}`
  (default `{}`); CDP for web/electron; **iOS/macOS already read `AXValue` (ios.py:146) but collapse
  it into the label — expose it structurally**; Flutter `Semantics(toggled)`. *Spine of the state-delta oracles.*
- `source_scan.py` — also capture init-state literals (`int _count = 0`), validation rules, empty-copy.
- `server.py` — new `@mcp.tool test_feature(repo_path, feature=None, diff=None, changed_files=None, surface=None, baseline_ref="HEAD~1", max_regions=8, max_hypotheses=8)`; clones the `test_app` envelope. `test_app` untouched.
**Reuse as-is:** `expectations.check_expectations/_norm`, `detection.scan_logs/finding_signature`,
`eval._semantic_mapping`, `build_finding`/`Finding.suspected_area`, `perception/som.py`,
`run_autopilot`, the `rigorous-ios-bugs` Workflow shape (fan-out → verify → synthesize).

## 9. Phased plan

| Phase | Deliverable | Target / proof |
|---|---|---|
| **0 — MVP spine** (web/electron) | `mapper.py` (CDP-landmark segmentation), `region_agent.py` w/ **LOGIC_ARITHMETIC + STATE_SYNC** only, `control_state` (CDP), `propose_hypotheses`, `test_feature` returning the FixItem contract. Sequential, no verifier (oracle already deterministic). | Catch `+2`-counter + toggle-desync on `sample-buggy-electron`, **zero self-injection** |
| **1 — gate + full lenses** | `verifier.py` (fresh-session replay + 2-of-2 + self-payload guard), `merger.py`, remaining 5 lenses (incl. inverted-polarity INPUT_VALIDATION). | **Eliminate the macOS 10-FP class**; raise Flutter recall from 1/3 |
| **2 — explore substrate** | `explore/state_graph.py` + `explore/selector.py` (Fastbot2 coverage selection, AutoDroid constrained actions); upgrade the exploratory `test_app` path + MAPPER traversal. | No more `no_progress` wander; deeper screens reached |
| **3 — oracle stack B/C** | `oracles/differential.py` (Genie+Odin), `oracles/sequence_oracle.py` (Trident, infer-first CoT). | Catch unmodeled silent bugs; the iOS a11y-state class |
| **4 — diff-aware + native + parallel** | `diff_scan.py` + `source_scan` extensions; `control_state` on iOS/macOS/Flutter; N-session parallel via `SessionManager` + Workflow. | Bounded regression sweep; full cross-surface matrix at parallel speed |

**Validation gate (every phase):** re-run `scripts/eval.py` in `test_feature` mode on
`sample-buggy-flutter` (today **1/3**) and `sample-buggy-macos` (today **0/3 + 10 FP**); the
acceptance bar is recall ↑ **and** the macOS false-positives → 0.

## 10. Risks (and mitigations)

- **Mapper quality is the new bottleneck** — canvas/sparse-a11y surfaces mis-segment. *Mitigation:*
  prefer the DOM-true CDP-landmark path on web/electron; let regions overlap rather than mis-exclude.
- **`control_state` must be wired per surface** or the desync oracles no-op. Native is low-risk
  (AXValue already read); Flutter `Semantics(toggled)` is the riskiest.
- **Cross-region bugs** (cause in A, symptom in B) fight strict bbox confinement. *Mitigation:* the
  NAVIGATION + PERSISTENCE lenses are deliberately granted multi-screen scope.
- **Cost** — `propose_hypotheses` per region + verifier replays + fix-writer ≫ the single loop.
  *Mitigation:* cap `max_regions`/`max_hypotheses`, 6-step budgets, cheaper `driver_model` for
  propose/verify, diff-scoping. True parallelism needs N sandboxes (N× billed).
- **Diff routing is heuristic** — a bug in *untouched* code triggered by the change can be scoped
  out. *Mitigation:* graceful full-sweep fallback + an optional 1-hypothesis smoke pass on unchanged regions.
- **The merge-stage semantic judge** is the only non-deterministic step; must be strict (over-eager
  collapse = recall loss).

## 11. References

AutoDroid (arXiv 2308.15272) · LLM-Explorer · Fastbot2 (ASE'22) · Genie (OOPSLA'21) · Odin ·
Trident (arXiv 2407.03037) · LLM-as-oracle limits (arXiv 2407.19053).
