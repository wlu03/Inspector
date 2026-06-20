# sample-buggy-app

A tiny Vite app used as the **M0 acceptance-test fixture** (see [docs/08](../../docs/08-roadmap.md)).

The **Save** button is supposed to show a green "Saved" toast, but it throws a
`TypeError` first — so the UI never updates. It's the canonical bug Inspector must
catch end to end:

1. `launch_app` boots it → `observe` returns a numbered screenshot.
2. `act` clicks the Save button (#N) → `changed: false` + a `TypeError` in the logs.
3. Inspector reports a reproducible finding → the host agent fixes `main.js` →
   re-verify → `changed: true`, toast appears → green.

Run it standalone with `npm install && npm run dev` (needs Node).
