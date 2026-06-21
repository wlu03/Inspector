# Planted bugs — sample-buggy-ios (v2: hard to surface)

Six deterministic, planted UI bugs across three screens. **None emits a log.** Each is
a subtle UI-STATE defect that only appears after a specific multi-step interaction and
is detectable solely by reading the accessibility tree — a `Text`'s content is its
`AXLabel`; a `TextField`'s typed contents are its `AXValue`. Greppable log signatures
have been removed precisely so an agent must *perceive and interact*, not scrape logs.

The machine-readable manifest is [`bugs.json`](./bugs.json). Each bug is confirmed
present by the a11y-state oracle in [`scripts/verify_ios_bugs.py`](../../scripts/verify_ios_bugs.py)
(drives the trigger sequence, asserts the present-vs-fixed condition) — `6/6` pass.

| ID | Screen | Category | Severity | Difficulty | Surfaced only by |
|----|--------|----------|----------|------------|------------------|
| BUG-01 | Profile  | state-sync        | high   | hard   | committing a name, leaving, returning, comparing two nodes |
| BUG-02 | Settings | input-edge        | medium | subtle | typing `007`, saving, re-reading the field value |
| BUG-03 | Settings | display-format    | low    | subtle | typing a known-length name, reading the counter |
| BUG-04 | Profile  | display-format    | low    | subtle | filling exactly 2 of 3 fields, reading the percent |
| BUG-05 | About    | navigation-focus  | high   | hard   | Continue → About, two Backs, reading the nav title |
| BUG-06 | Settings | control-mismatch  | medium | subtle | two segment taps, comparing highlight vs caption |

No first-paint tells: the empty Settings counter correctly reads `0/30`, the default
theme caption agrees with the highlight, and Profile starts blank. You have to *act*.

---

### BUG-01 — Committed Profile edits lost on re-entry (Profile · state-sync · hard)
- **Trigger:** On Profile, type `Wesley` into Display name + an email → **Continue**
  (navigates to About) → **Back** once to the (duplicate) Profile → read the
  **Saved profile** row and the Display name field.
- **Expected:** The field is re-seeded from the model and reads `Wesley`, matching the summary.
- **Actual:** The Saved-profile row reads `Wesley` (model-backed) but the Display name
  field is **empty** — a same-screen contradiction. The fields are fresh `@State` with no
  `.onAppear` read-back, so the committed edit appears lost.
- **a11y oracle:** PRESENT iff a node `AXLabel == "Wesley"` exists AND the Display name
  field `AXValue` is empty; FIXED iff both are `Wesley`.

### BUG-02 — Save Int-normalizes the name (Settings · input-edge · subtle)
- **Trigger:** Type `007` into **Your name** → **Save** → re-read the field + confirmation.
- **Expected:** The name persists verbatim (`007`) and **Saved** appears.
- **Actual:** `Int("007")` → the field silently re-renders to `7` while the green **Saved**
  still claims success. Leading zeros vanish.
- **a11y oracle:** PRESENT iff field `AXValue == "7"` AND a `Saved` confirmation shows.

### BUG-03 — Character counter off-by-one (Settings · display-format · subtle)
- **Trigger:** Note the empty-field counter reads `0/30` → type exactly `Alice` (5) →
  read the counter.
- **Expected:** `5/30`.
- **Actual:** `4/30` — the counter renders `max(0, count - 1)/30`, so it's boundary-safe at
  empty (no first-paint tell) but undercounts every non-empty value by one.
- **a11y oracle:** PRESENT iff after an N-char value the counter leading int `== N-1`.

### BUG-04 — Completeness percent truncates (Profile · display-format · subtle)
- **Trigger:** On Profile, fill exactly two of three fields (Display name + Email, leave
  Phone empty) → read **Profile completeness**.
- **Expected:** `67%` (round of 66.67).
- **Actual:** `66%` — `filled * 100 / 3` integer division truncates.
- **a11y oracle:** PRESENT iff the percent `== 66`; FIXED iff `== 67`.

### BUG-05 — Continue pushes a duplicate Profile (About · navigation-focus · hard)
- **Trigger:** On Profile, type a name + email → **Continue** (lands on About) → tap
  **Back** twice → read the nav title.
- **Expected:** Two Backs reach the **Settings** root (no Back button).
- **Actual:** Continue pushes a stray duplicate Profile (stack: Profile › Profile › About),
  so two Backs leave you on a **Profile** with a Back button still present — the stack is
  one screen too deep, and the intermediate Profile is blank (see BUG-01).
- **a11y oracle:** PRESENT iff after two Backs nav-title `== "Profile"` with a Back button.

### BUG-06 — Theme control applies the previous selection (Settings · control-mismatch · subtle)
- **Trigger:** Tap the **Light** theme segment → tap **Dark** → compare the highlighted
  segment to the **Current theme:** caption.
- **Expected:** The caption matches the highlight (`Dark`).
- **Actual:** The segmented control's `onChange` writes `oldValue`, so the caption reads
  `Current theme: Light` while `Dark` is highlighted — they disagree by one tap.
- **a11y oracle:** PRESENT iff after Light→Dark the caption reads `Light` (`!=` highlight).

---

**Non-bugs (precision traps).** About's **Reset all** now works correctly (clears state,
returns to root). An agent that flags it is wrong.
