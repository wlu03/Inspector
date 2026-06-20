# infra — execution planes (the VMs)

Everything Inspector drives runs **inside a VM**, never on your host. Because the
iOS Simulator requires macOS, there are **two planes**:

| Plane | VM | Surfaces | Dir |
|---|---|---|---|
| **Linux** | E2B Desktop microVM | web, Electron, **Android** (Redroid) | [linux-e2b/](linux-e2b/) · [android-redroid/](android-redroid/) |
| **macOS** | tart VM on Apple silicon | **iOS** (Xcode Simulator + idb) | [macos-tart/](macos-tart/) |
| _(alt iOS)_ | Corellium (virtual real iOS) | iOS | [ios-corellium/](ios-corellium/) |

The `inspector/planes/` module is the code abstraction over these
(`LinuxPlane`, `MacOSPlane`, `RedroidRuntime`). iOS **cannot** share the Linux
plane — that's Apple licensing + the fact the Simulator is macOS-only.

## Whole-system options

- **A — Linux VM + your own macOS VM (tart on Apple silicon).** Most control, cheapest if you own Apple hardware.
- **B — Linux VM + Corellium.** No Mac to manage; highest iOS fidelity; highest cost.
- **C — Linux VM + cloud Mac (MacStadium Orka / AWS EC2 Mac).** Fully managed; ongoing cost.

Recommended: **A** — one E2B Linux plane (web/Electron/Android) + one tart macOS VM (iOS).
