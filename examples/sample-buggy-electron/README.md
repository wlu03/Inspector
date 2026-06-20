# sample-buggy-electron

M0 fixture for the **Electron** surface (Linux plane). Same bug as the web sample:
the **Save** button should show a green "Saved" toast but throws a `TypeError`
first, so nothing updates.

LoopBack catches it two ways:
- the **renderer console** via CDP (`--remote-debugging-port=9223`) → the `TypeError`,
- **verify-after-act** → no confirmation appears.

Driven by `loopback/adapters/electron.py` (task #8) inside the E2B Linux plane.

Run standalone (needs Node + a display): `npm install && npm run dev`.
