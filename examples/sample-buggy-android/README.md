# sample-buggy-android

A small, deliberately-buggy Expo / React Native app used as a **deterministic
test fixture** for an automated UI-testing agent. Three screens with
navigation, six planted bugs, zero backend, and no dependencies beyond the
Expo/RN defaults. Navigation and shared state use standard React idioms (a tiny
state-based navigator + React Context) — **no `@react-navigation`, no extra
deps**. Everything reproduces on every run.

This is the **Android** surface fixture (Redroid, Linux plane). The agent
catches failures via **logcat** (tag `ReactNativeJS`) / **Metro** and a
**verify-after-act** check.

## Screens & intended behavior

A top nav bar switches between three screens:

1. **Settings**
   - "Your name" text input.
   - "Save" button → should show a **"Saved"** confirmation.
   - "Notifications" toggle (Off/On) → should flip the label **and** the
     underlying state.
   - "Theme" picker (Light / Dark / System) → switches the color scheme
     (this one works correctly).
2. **Profile**
   - "Display name" (required) and "Email" (must contain "@") inputs.
   - "Continue" button → should validate before proceeding.
   - A read-only **Summary** that should reflect the name typed on Settings.
3. **About**
   - Static app info and a version string (`1.0.0`).
   - "Reset all" button → should clear all state and return to Settings.

## Planted bugs

Six deterministic bugs. Full machine-readable manifest the agent is scored
against: **[`bugs.json`](./bugs.json)** (also human-readable
**[`BUGS.md`](./BUGS.md)**). Each emits a distinct, greppable `console.error`
line **before** its faulty behavior.

| ID | Screen | Category | Severity | Difficulty | Log signature |
|----|--------|----------|----------|------------|---------------|
| BUG-01 | Settings | crash | critical | obvious | `query not invalidated after save` |
| BUG-02 | Settings | silent-state | medium | subtle | `toggle state desync` |
| BUG-03 | Profile | validation-bypass | high | obvious | `validation skipped on submit` |
| BUG-04 | Profile | cross-screen-state | high | subtle | `state not propagated across screens` |
| BUG-05 | About | navigation | medium | obvious | `reset no-op, wrong route` |
| BUG-06 | Settings | a11y-locator-trap | medium | subtle | `missing a11y label on primary action` |

## Dev / run command

One command via the standard Expo dev server:

```bash
npm install
npx expo start
```

Then open on Android (press `a` for an emulator/device, or scan the QR with
Expo Go). Crashes and logs surface in **Metro** and in **logcat**.

## Expected log / crash signatures

All six log lines are emitted via `console.error`, which maps to logcat tag
`ReactNativeJS` at level `E` (and to the Metro console):

```
ERROR  missing a11y label on primary action          # BUG-06, on Settings mount
ERROR  query not invalidated after save               # BUG-01, on Save tap
TypeError: undefined is not an object (evaluating 'result.show')   # BUG-01 crash
ERROR  toggle state desync                            # BUG-02, on Notifications tap
ERROR  state not propagated across screens            # BUG-04, on Profile mount
ERROR  validation skipped on submit                   # BUG-03, on Continue tap
ERROR  reset no-op, wrong route                       # BUG-05, on Reset all tap
```

Only **BUG-01** produces an uncaught crash; the other five are non-crashing
behavioral defects detectable by their log line + a verify-after-act check.

## Building an APK for Redroid

For the Redroid pipeline (instead of `expo start`):

```bash
npx expo prebuild -p android
cd android && ./gradlew assembleDebug
adb install -r -t app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.inspector.samplebuggyandroid/.MainActivity
```

Driven by `inspector/adapters/android.py` (task #9). See
[`../../infra/android-redroid/`](../../infra/android-redroid/).
