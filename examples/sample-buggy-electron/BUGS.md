# Planted bugs — sample-buggy-electron

Scored manifest for the automated UI-testing agent. Machine-readable version:
[`bugs.json`](./bugs.json). Each bug emits a distinct `console.error` line
**before** its faulty behavior; lines are observable over CDP
(`--remote-debugging-port=9223`).

| ID | Screen | Category | Severity | Difficulty | Log signature |
|----|--------|----------|----------|------------|---------------|
| BUG-01 | Settings | crash | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | silent-state | low | subtle | `toggle state desync` |
| BUG-03 | Profile | validation-bypass | high | subtle | `validation skipped on submit` |
| BUG-04 | Profile | broken-cross-screen-state | medium | subtle | `state not propagated across screens` |
| BUG-05 | About | navigation-defect | high | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | a11y/locator-trap | low | subtle | `missing a11y label on primary action` |

---

### BUG-01 — Save crashes (critical, obvious)
- **Trigger:** Settings → type a name → click the real Save button.
- **Expected:** Name saved; green "Saved" confirmation appears.
- **Actual:** Uncaught `TypeError` (method on `undefined`); "Saved" never appears.
- **Log:** `query not invalidated after save`
- **Crash:** `TypeError: Cannot read properties of undefined (reading 'show')`

### BUG-02 — Notifications toggle desync (low, subtle)
- **Trigger:** Settings → click the "Notifications" toggle.
- **Expected:** Toggle flips and underlying state updates to match.
- **Actual:** Only the visual label flips; `store.notifications` never changes. No crash.
- **Log:** `toggle state desync`

### BUG-03 — Validation bypass on Continue (high, subtle)
- **Trigger:** Profile → leave Display name empty, enter email without "@" → Continue.
- **Expected:** Submission blocked (Display name required; Email must contain "@").
- **Actual:** Validation skipped; proceeds as if valid.
- **Log:** `validation skipped on submit`

### BUG-04 — Profile summary not propagated (medium, subtle)
- **Trigger:** Set a name on Settings → navigate to Profile → read the summary.
- **Expected:** Summary shows the name saved on Settings.
- **Actual:** Summary reads a never-updated cache → always blank/stale.
- **Log:** `state not propagated across screens`

### BUG-05 — Reset all no-op + wrong route (high, obvious)
- **Trigger:** About → click "Reset all".
- **Expected:** State cleared and returns to Settings.
- **Actual:** Nothing cleared; routes to the wrong screen (Profile).
- **Log:** `reset no-op, wrong route`

### BUG-06 — Save locator trap (low, subtle)
- **Trigger:** Settings → locate the Save control by visible/accessible label "Save" and click.
- **Expected:** Primary Save action runs (see BUG-01).
- **Actual:** The "Save" label is on a decorative element; the real button has no
  accessible name, so naive locators hit the decoy, which does nothing.
- **Log:** `missing a11y label on primary action`
