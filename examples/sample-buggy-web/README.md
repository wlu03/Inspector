# sample-buggy-web

A tiny, deterministic, deliberately-buggy web app used as a test fixture for an
automated UI-testing agent. Built with **Vite + vanilla HTML/JS** — no backend,
no network, no database, and no dependencies beyond Vite. Everything reproduces
on every run.

## Run

```bash
npm install
npm run dev
```

Then open the printed local URL (default http://localhost:5173/). Navigation is
hash-based: `#/settings`, `#/profile`, `#/about`.

## Screens & intended behavior

1. **Settings** (`#/settings`) — a "Your name" text input + a **Save** button
   that should show a `Saved: <name>` confirmation, a **Notifications** toggle
   (On/Off), and a **Theme** picker (Light / Dark / System).
2. **Profile** (`#/profile`) — a form with **Display name** (required) and
   **Email** (must contain `@`), a **Continue** button that should reject invalid
   input, and a read-only summary that should reflect the name saved on Settings.
3. **About** (`#/about`) — static app info, a version string, and a **Reset all**
   button that should clear state and return to Settings.

## Planted bugs

Six bugs, varied in type and severity. The scored ground truth lives in
[`BUGS.md`](./BUGS.md) and [`bugs.json`](./bugs.json) (each entry has `id`,
`screen`, `trigger`, `expected`, `actual`, `severity`, `difficulty`, and
`log_signature`). Each bug emits its distinct log line **before** the faulty
behavior.

| ID | Screen | Type | Severity | Difficulty |
|----|--------|------|----------|------------|
| BUG-01 | Settings | crash on Save | critical | obvious |
| BUG-02 | Settings | notifications toggle desync | medium | subtle |
| BUG-03 | Profile | validation bypass | high | subtle |
| BUG-04 | Profile | summary not propagated across screens | high | subtle |
| BUG-05 | About | Reset all no-op + wrong route | medium | obvious |
| BUG-06 | Settings | a11y / locator trap on Save | medium | subtle |

## Expected log / crash signatures

All log lines are emitted via `console.error` (browser console):

```
query not invalidated after save        # BUG-01, then:
Uncaught TypeError: Cannot read properties of undefined (reading 'invalidate')
toggle state desync                     # BUG-02
validation skipped on submit            # BUG-03
state not propagated across screens     # BUG-04
reset no-op, wrong route                # BUG-05
missing a11y label on primary action    # BUG-06 (logged on Settings render)
```
