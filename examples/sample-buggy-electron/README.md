# sample-buggy-electron

Deliberately-buggy, multi-screen **Electron** fixture for an automated
UI-testing agent. Deterministic, self-contained, one command to run — no
backend, no network, no database. Everything reproduces on every run.

## Screens & intended behavior

Navigation uses the standard hash-router idiom (`#/settings`, `#/profile`,
`#/about`); state lives in a plain in-memory object.

1. **Settings** — "Your name" input + Save button + "Saved" confirmation area, a
   "Notifications" toggle, and a "Theme" picker (Light/Dark/System). Saving
   *should* store the name and show "Saved"; the theme picker works.
2. **Profile** — a form with "Display name" (required), "Email" (must contain
   "@"), and a "Continue" button, plus a read-only summary that *should* reflect
   the name saved on Settings.
3. **About** — static app info, a version string, and a "Reset all" button that
   *should* clear state and return to Settings.

## Planted bugs

Six deterministic bugs. Each emits a distinct `console.error` line **before** its
faulty behavior. Full scored manifest: [`BUGS.md`](./BUGS.md) /
[`bugs.json`](./bugs.json).

| ID | Screen | Category | Severity | Difficulty | Log signature |
|----|--------|----------|----------|------------|---------------|
| BUG-01 | Settings | crash | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | silent-state | low | subtle | `toggle state desync` |
| BUG-03 | Profile | validation-bypass | high | subtle | `validation skipped on submit` |
| BUG-04 | Profile | broken-cross-screen-state | medium | subtle | `state not propagated across screens` |
| BUG-05 | About | navigation-defect | high | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | a11y/locator-trap | low | subtle | `missing a11y label on primary action` |

BUG-01 also throws an uncaught crash:
`TypeError: Cannot read properties of undefined (reading 'show')`.

## Run

Needs Node + a display (or a virtual one such as Xvfb on Linux):

```sh
npm install
npm run dev      # = electron .
```

The main process enables `--remote-debugging-port=9223` (see `main.js`) so the
renderer console is observable over CDP.

## Expected log / crash signatures

All emitted on the **renderer console** (`console.error`) when each bug's
trigger is exercised:

- `query not invalidated after save` + `TypeError: Cannot read properties of undefined (reading 'show')`
- `toggle state desync`
- `validation skipped on submit`
- `state not propagated across screens`
- `reset no-op, wrong route`
- `missing a11y label on primary action`
