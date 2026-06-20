# Planted bug manifest — sample-buggy-web

Machine-readable companion: [`bugs.json`](./bugs.json). This is the ground truth
an automated UI-testing agent is scored against. Six bugs, varied type and
severity. Each emits a distinct, greppable `console.error` line **before** its
faulty behavior.

| ID | Screen | Type | Severity | Difficulty | Log signature |
|----|--------|------|----------|------------|---------------|
| BUG-01 | Settings | crash | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | silent-state | medium | subtle | `toggle state desync` |
| BUG-03 | Profile | validation-bypass | high | subtle | `validation skipped on submit` |
| BUG-04 | Profile | broken-cross-screen-state | high | subtle | `state not propagated across screens` |
| BUG-05 | About | navigation-defect | medium | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | a11y-locator-trap | medium | subtle | `missing a11y label on primary action` |

---

## BUG-01 — Save crashes (critical, obvious)

- **Screen:** Settings
- **Trigger:** Type any value into "Your name", then click the Save button (the 💾 button, `id=primary-action`).
- **Expected:** The `Saved: <name>` confirmation appears in `#saved`.
- **Actual:** An uncaught `TypeError` is thrown (`queryCache` is `undefined`) before the confirmation renders; `#saved` stays empty.
- **Log:** `query not invalidated after save`
- **Crash:** `Uncaught TypeError: Cannot read properties of undefined (reading 'invalidate')`

## BUG-02 — Notifications toggle desync (medium, subtle)

- **Screen:** Settings
- **Trigger:** Click the Notifications toggle button.
- **Expected:** The toggle label flips **and** `state.notifications` updates to match.
- **Actual:** The visual label flips between On/Off but `state.notifications` never changes (always `false`). No crash.
- **Log:** `toggle state desync`

## BUG-03 — Validation bypass on Continue (high, subtle)

- **Screen:** Profile
- **Trigger:** Leave "Display name" empty and/or enter an email without `@`, then click Continue.
- **Expected:** Submission is blocked until Display name is non-empty and Email contains `@`.
- **Actual:** Invalid input is accepted; the form proceeds and shows `Continued ✓` as if valid.
- **Log:** `validation skipped on submit`

## BUG-04 — Profile summary not propagated (high, subtle)

- **Screen:** Profile
- **Trigger:** Save a name on Settings (BUG-01 crashes the save, but `state.savedName` is still captured), then navigate to Profile and read the summary.
- **Expected:** The summary reads `Name from Settings: <name>`.
- **Actual:** The summary always renders blank because it reads from `profileMirror`, which nothing ever writes.
- **Log:** `state not propagated across screens`

## BUG-05 — Reset all no-op / wrong route (medium, obvious)

- **Screen:** About
- **Trigger:** Click "Reset all".
- **Expected:** All state is cleared and the app routes back to Settings.
- **Actual:** Nothing is cleared and the app routes to `#/gone`, an unknown route that renders an empty dead-end screen.
- **Log:** `reset no-op, wrong route`

## BUG-06 — A11y / locator trap on Save (medium, subtle)

- **Screen:** Settings
- **Trigger:** Use a naive locator (by text "Save" or `[data-testid=save-button]`) to find and click the Save action.
- **Expected:** The primary Save action carries the accessible name / test id matched by "Save".
- **Actual:** The real button (💾, `id=primary-action`) has no accessible label/test id; a non-clickable decorative span carries the "Save" text and `data-testid=save-button`, so naive locators hit the wrong element.
- **Log:** `missing a11y label on primary action`
