# Planted bugs — sample-buggy-android

Machine-readable companion: [`bugs.json`](./bugs.json). This is the manifest an
automated UI-testing agent is scored against. Every bug is deterministic and
reproduces on every run. Each emits a distinct, greppable log line via
`console.error` **before** its faulty behavior; on Android these surface in
**logcat** (tag `ReactNativeJS`) and in the **Metro** console.

| ID | Screen | Category | Severity | Difficulty | Log signature |
|----|--------|----------|----------|------------|---------------|
| BUG-01 | Settings | crash | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | silent-state | medium | subtle | `toggle state desync` |
| BUG-03 | Profile | validation-bypass | high | obvious | `validation skipped on submit` |
| BUG-04 | Profile | cross-screen-state | high | subtle | `state not propagated across screens` |
| BUG-05 | About | navigation | medium | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | a11y-locator-trap | medium | subtle | `missing a11y label on primary action` |

---

## BUG-01 — Save crashes before confirmation (crash, critical, obvious)

- **Screen:** Settings
- **Trigger:** Type any value into "Your name", then tap the blue **Save**
  Pressable (not the decorative "Save ✓" text).
- **Expected:** A "Saved" confirmation appears below the button.
- **Actual:** An uncaught `TypeError` is thrown on press; "Saved" never renders.
- **Log signature:** `query not invalidated after save`
- **Crash signature:** `TypeError: undefined is not an object (evaluating 'result.show')`

## BUG-02 — Notifications toggle desync (silent-state, medium, subtle)

- **Screen:** Settings
- **Trigger:** Tap the Notifications toggle (shows "Off").
- **Expected:** Label flips **and** the underlying notifications state updates.
- **Actual:** Label flips to "On" but the underlying state stays "disabled"
  (see the `(underlying state: disabled)` line). No crash.
- **Log signature:** `toggle state desync`

## BUG-03 — Validation bypass on Continue (validation-bypass, high, obvious)

- **Screen:** Profile
- **Trigger:** Leave "Display name" empty and enter an email with no "@" (or
  leave it empty), then tap **Continue**.
- **Expected:** Submission is blocked (Display name required; Email must contain "@").
- **Actual:** Validation is skipped; status shows "Continuing… (accepted)".
- **Log signature:** `validation skipped on submit`

## BUG-04 — Settings name not propagated to Profile (cross-screen-state, high, subtle)

- **Screen:** Profile
- **Trigger:** Type a name on Settings, navigate to Profile, read the
  "Name from Settings:" summary line.
- **Expected:** The summary shows the name typed on Settings.
- **Actual:** The summary is always blank — it reads a local empty variable
  instead of shared context state.
- **Log signature:** `state not propagated across screens`

## BUG-05 — Reset all is a no-op with wrong route (navigation, medium, obvious)

- **Screen:** About
- **Trigger:** Tap **Reset all**.
- **Expected:** All state (name, theme) is cleared and the app routes to Settings.
- **Actual:** Nothing is cleared and the app routes to a dead-end blank screen
  ("Nothing here.").
- **Log signature:** `reset no-op, wrong route`

## BUG-06 — Save button locator trap (a11y-locator-trap, medium, subtle)

- **Screen:** Settings (logged on mount)
- **Trigger:** Attempt to locate the Save button by accessible label or testID
  `save-button`.
- **Expected:** The primary Save action carries the accessible label / testID
  `save-button`.
- **Actual:** A decorative, non-interactive "Save ✓" `Text` carries
  label/testID `save-button`; the real Save `Pressable` has `accessible={false}`
  and no testID, so naive locators hit the wrong element.
- **Log signature:** `missing a11y label on primary action`
