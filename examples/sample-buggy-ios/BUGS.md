# Planted bugs — sample-buggy-ios

Six deterministic, planted bugs across three screens. The agent is scored against
this list; the machine-readable copy is [`bugs.json`](./bugs.json). Each bug emits a
distinct, greppable log line (`NSLog`) **before** its faulty behavior.

| ID | Screen | Type | Severity | Difficulty | Log signature |
|----|--------|------|----------|------------|---------------|
| BUG-01 | Settings | crash | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | silent state | medium | subtle | `toggle state desync` |
| BUG-03 | Profile | validation bypass | high | subtle | `validation skipped on submit` |
| BUG-04 | Profile | cross-screen state | medium | subtle | `state not propagated across screens` |
| BUG-05 | About | navigation defect | high | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | a11y / locator trap | medium | subtle | `missing a11y label on primary action` |

---

### BUG-01 — Save crashes (Settings)
- **Trigger:** Open Settings → type any name → tap **Save**.
- **Expected:** A green **"Saved"** confirmation appears below the field.
- **Actual:** Logs `query not invalidated after save`, then crashes with
  `Fatal error: Index out of range` (reads `items[5]` on an empty array) before the
  confirmation is set. "Saved" never appears.

### BUG-02 — Notifications toggle desync (Settings)
- **Trigger:** Open Settings → tap the **Notifications** toggle.
- **Expected:** The label flips **and** `app.notificationsEnabled` updates to match.
- **Actual:** Logs `toggle state desync`; the visual label flips On/Off but the
  underlying `notificationsEnabled` stays `false`. No crash.

### BUG-03 — Validation bypass (Profile)
- **Trigger:** Open Profile → leave **Display name** empty → enter an **Email** with no
  `@` (e.g. `foo`) → tap **Continue**.
- **Expected:** Continue is blocked (Display name required, Email must contain `@`).
- **Actual:** Logs `validation skipped on submit`, then proceeds as if valid and shows
  the Result section.

### BUG-04 — State not propagated across screens (Profile)
- **Trigger:** On Settings, type a name → navigate to Profile → read the
  **"Saved from Settings"** summary.
- **Expected:** The summary shows the name entered on Settings.
- **Actual:** Logs `state not propagated across screens`; the summary always renders
  blank (`—`). The name never crosses screens.

### BUG-05 — Reset routes wrong (About)
- **Trigger:** Open About → tap **Reset all**.
- **Expected:** All state clears and the app returns to the Settings root.
- **Actual:** Logs `reset no-op, wrong route`; nothing is cleared and the app pushes the
  wrong screen (Profile) instead of resetting to Settings.

### BUG-06 — Missing a11y label on primary action (Settings)
- **Trigger:** Open Settings → locate the primary **Save** action by accessible
  label / test id.
- **Expected:** The functional Save button exposes an accessible label/id of `Save`.
- **Actual:** Logs `missing a11y label on primary action` (on screen appear); the real
  Save button has no accessible label and no test id, while a decorative seal badge
  carries label/id `Save`. Naive locators tap the wrong (dead) element.
