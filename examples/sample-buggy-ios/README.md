# sample-buggy-ios

A small, deliberately-buggy **SwiftUI** app used as a **test fixture** for the
automated UI-testing agent. iOS surface (macOS plane). Three screens, six planted
bugs, fully deterministic — no backend, no network, no persistence. Every field
resets to its default on launch, so all bugs reproduce on every run.

Built with standard SwiftUI idioms only: `NavigationStack` for navigation, an
`ObservableObject` (`AppState`) plus `@State` for state. Logging uses `NSLog`; the
crash idiom is array index-out-of-range.

## Screens & intended behavior

1. **Settings** (root) — "Your name" field, a **Save** button with a green "Saved"
   confirmation area, a **Notifications** toggle, and a **Theme** picker
   (Light/Dark/System). The Theme picker genuinely works (it drives the color
   scheme); it's the working control to contrast against the broken ones.
2. **Profile** — a form with **Display name** (required), **Email** (must contain
   `@`), and a **Continue** button, plus a read-only **"Saved from Settings"**
   summary that should reflect the name entered on Settings.
3. **About** — static app info, a version string (`1.0.0 (M0)`), and a **Reset all**
   button that should clear state and return to Settings.

Navigation: Settings links to Profile and About; About's Reset is meant to pop back
to the Settings root.

## Planted bugs

Six deterministic bugs, each emitting a distinct greppable `NSLog` line before its
faulty behavior. Full details (trigger steps, expected/actual, severity, difficulty)
are in [`BUGS.md`](./BUGS.md); the machine-readable manifest the agent is scored
against is [`bugs.json`](./bugs.json).

| ID | Screen | Type | Severity | Difficulty | Log signature |
|----|--------|------|----------|------------|---------------|
| BUG-01 | Settings | crash on Save | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | toggle silent state desync | medium | subtle | `toggle state desync` |
| BUG-03 | Profile | validation bypass | high | subtle | `validation skipped on submit` |
| BUG-04 | Profile | cross-screen state blank/stale | medium | subtle | `state not propagated across screens` |
| BUG-05 | About | reset no-op + wrong route | high | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | missing a11y label on Save | medium | subtle | `missing a11y label on primary action` |

## Build + run on the Simulator (one command)

Requires Xcode with an iOS simulator runtime and
[`xcodegen`](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`). From
this directory:

```bash
./run.sh
```

This generates `SampleBuggyApp.xcodeproj`, builds for the simulator, installs, and
launches with the console attached. Equivalent manual steps:

```bash
xcodegen generate              # -> SampleBuggyApp.xcodeproj
xcodebuild -scheme SampleBuggyApp -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
# artifact: build/Build/Products/Debug-iphonesimulator/SampleBuggyApp.app
xcrun simctl install booted build/Build/Products/Debug-iphonesimulator/SampleBuggyApp.app
xcrun simctl launch --console booted com.inspector.SampleBuggyApp
```

## Expected log / crash signatures

Watch the simulator log via the `--console` output above,
`xcrun simctl spawn booted log stream --predicate 'process == "SampleBuggyApp"'`, or
(for the crash) a report under `~/Library/Logs/DiagnosticReports/`. Each bug logs
its line; only BUG-01 also crashes:

```
query not invalidated after save          # BUG-01, immediately followed by:
Fatal error: Index out of range
... Thread N: EXC_BREAKPOINT / SIGTRAP (Swift runtime trap: index out of range)
toggle state desync                       # BUG-02
validation skipped on submit              # BUG-03
state not propagated across screens       # BUG-04
reset no-op, wrong route                  # BUG-05
missing a11y label on primary action      # BUG-06 (logged when Settings appears)
```

The agent detects BUG-01 via the crash (simulator log / DiagnosticReports) and the
rest via **verify-after-act** — the observed UI/state never matches the expected
outcome (no "Saved", toggle state unchanged, invalid form accepted, blank summary,
wrong screen after reset, decoy element under the "Save" locator).

Driven by `inspector/adapters/ios.py`. See [`../../infra/macos-tart/`](../../infra/macos-tart/).
