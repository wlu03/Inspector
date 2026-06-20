# iOS plane (alternative) — Corellium

Corellium runs **virtualized real iOS** (ARM) in their cloud or an on-prem
appliance — the truest "iOS in a VM," with no Mac to manage. Higher fidelity than
the Simulator (real iOS frameworks, root/jailbreak, snapshots) and higher cost.

Use this instead of [../macos-tart/](../macos-tart/) when you need real-device
behavior or want zero Apple-hardware management.

## Shape (scaffold)
- Auth + create a device via the Corellium REST API.
- Drive it: their API exposes screenshot, input (tap/swipe/text), app install,
  and console — map these to the `IOSAdapter` contract just like simctl/idb.
- Config: copy `config.example.json` and set your API endpoint + token.

## Code
- `loopback/planes/` — add a `CorelliumPlane` implementing `ExecutionPlane`.
- `loopback/adapters/ios.py` — the adapter targets either `MacOSPlane` or `CorelliumPlane`.

> This is a documented option, not the default. Start with macos-tart unless you
> specifically need real-iOS fidelity.
