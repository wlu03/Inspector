# 05 — Detection & Feedback

## Governing principle

**Acting is buildable; judging is research-hard.** Every deterministic, objective signal is cheap and reliable. The unsolved bottleneck is the **oracle problem** — deciding whether a flagged anomaly is a *real bug* vs. intended behavior. Empirically, LLM-as-bug-judge precision was ~31% (≈69% false positives) vs. ~100% for deterministic checks. So: deterministic signals are authoritative; the LLM assists on judgment but is **never the sole pass/fail authority** in an unattended loop.

## Detection channels

### Deterministic (high confidence — build first)
| Signal | Source | Effort |
|---|---|---|
| Crash / exception | log tap (stdout/stderr, logcat, idevicesyslog) | S |
| Console / network errors (web) | browser console capture (no Playwright needed — read stdout or a thin console hook) | S |
| Accessibility violations | axe-core (web) | S |
| Broken navigation / dead-end | observe URL/state not changing after action | M |
| Layout anomaly | element-bbox geometry (overlap, off-screen, truncation) | M |

### Visual / judgment (host-assisted, confidence-gated)
- **Pixel diff** vs. a baseline (`pixelmatch`) to flag *changed regions* — high false-positive rate alone.
- Hand the before/after crops to the **host VLM** to judge "real regression vs. intended change."
- **Confidence gate:** for visual findings, K-sample the host's judgment (ask twice, require agreement) before asserting a bug.

> The log tap is the most valuable, most reliable bug signal and it is **not Playwright** — it's just reading the output of the process you already launched. Keep it even though all *interaction* is computer-use; it catches the silent errors the eyes can't see.

## Directed vs. exploratory

- **Directed verification (v0):** "the agent just changed X — confirm X works and didn't break neighbors." Reliable, ships now. The oracle is "expected change happened / no new error."
- **Exploratory bug-finding (v2 moonshot):** "go find issues I don't know about." Scope to a **crash/invariant oracle** (objective), never open-ended functional correctness (drowns in hallucinated bugs; best models score <16% on proactive-bug benchmarks).

## Finding synthesis

Constrained-JSON finding the host can act on:

```jsonc
{
  "summary": "Save button shows no confirmation",
  "surface": "web",
  "severity": "medium",
  "confidence": "high",          // deterministic = high, visual = lower
  "repro": ["open /settings", "click element #7 (Save)", "observe no toast"],
  "expected": "a 'Saved' toast appears",
  "actual": "no visual change; console: 'mutation succeeded' but no UI update",
  "logs": ["[warn] query not invalidated after save"],
  "suspected_area": "useSaveSettings mutation onSuccess",
  "screenshot_refs": ["frame_0012.png", "frame_0013.png"],
  "trace_id": "trc_abc123"
}
```

## Reproducibility / replay

- **The action log IS the re-run script** — replay the recorded action sequence post-fix to confirm green (deterministic).
- **Determinism controls:** seed RNG/UUIDs, freeze the clock, replay network from a recorded HAR where needed.
- **Trace artifacts:** per-action screenshots + logs + actions, written to a trace folder (see [06](06-data-schema.md)). For web, optionally rrweb — but note rrweb *reconstructs* visually, it does **not** re-execute, so it cannot verify a fix.

## Loop guardrails (solved engineering — build all of these)

1. **Hard caps** — max iterations, max wall-clock, max cost per session. (Raising the cap is not a fix.)
2. **No-progress detection** — hash `(action, post-screenshot, logs)`; repeated identical states → escalate, don't keep looping.
3. **Confidence gate** — K-sample self-consistency for judgment calls, not raw verbalized confidence (LLMs are overconfident).
4. **Deterministic verifier-in-the-loop** — reproduce the bug before fixing; after the fix, the repro must pass *and* the pre-fix state must still have failed.
5. **False-heal guard** — never let "an element now matches" count as "bug fixed."
6. **Terminal HITL** — open a **PR / draft, never auto-merge.** This single guardrail bounds the blast radius of the unavoidable false positives.
