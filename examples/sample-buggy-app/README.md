# sample-buggy-app — Acme Workspace

A small but **multi-screen** Vite web app used as an Inspector test fixture. It now has
a sidebar and seven screens (Dashboard, Tasks, Cart, Profile, Settings, Billing, About),
each planting a **different class of bug** so the agent's oracles get full coverage.

Run it standalone:

```bash
npm install && npm run dev      # vite → http://localhost:5173
```

Or drive it headless through Inspector (no build needed — it's vanilla ES modules):

```bash
INSPECTOR_WEB_DIST=examples/sample-buggy-app \
  python scripts/test_one.py examples/sample-buggy-app web 12
# or the planner + parallel agents:
INSPECTOR_WEB_DIST=examples/sample-buggy-app \
  python scripts/demo_planner.py examples/sample-buggy-app web 4 6
```

## Planted bugs (see `bugs.json` for the machine-readable manifest — **do not fix**)

| ID | Screen | Class | What's wrong |
|----|--------|-------|--------------|
| BUG-01 | Settings | crash | Save throws a `TypeError` before the "Saved" toast (the original M0 bug). |
| BUG-02 | Profile | input-integrity | Username field strips spaces — type "Wesley Lu", it stores "WesleyLu". |
| BUG-03 | Profile | validation-bypass | Save accepts any email (empty / no `@`) and says success. |
| BUG-04 | Settings | state-not-persisted | Theme resets after navigating away and back. |
| BUG-05 | Tasks | logic | "N active" badge counts completed tasks too. |
| BUG-06 | Cart | arithmetic | Total sums quantities, ignores price ($3.00 instead of $28.50). |
| BUG-07 | Cart | validation-bypass | "Place order" succeeds with an empty cart. |
| BUG-08 | Settings | state-desync | Notifications toggle flips visually but never updates state. |
| BUG-09 | About | missing-element | The "Export data" button is specified but never rendered. |
| BUG-10 | Billing | dead-control | "Cancel subscription" has no handler — clicking does nothing. |
| BUG-11 | Reports | arithmetic | Task completion always shows 100% (divides done by done). |
| BUG-12 | Team | validation-bypass | Invite accepts an empty email and adds a blank member. |
| BUG-13 | Team | wrong-target | Remove deletes the first member, not the one clicked. |

These span every oracle Inspector ships: deterministic log/crash tap (BUG-01), verify-
after-act / dead-control (BUG-01, BUG-10), input-integrity (BUG-02), code-aware
missing-element (BUG-09), cross-screen state (BUG-04, BUG-08), and brain judgment for
logic/arithmetic/validation (BUG-03, BUG-05, BUG-06, BUG-07).
