# sample-buggy-ios

M0 fixture for the **iOS** surface (macOS plane). A SwiftUI app with the same bug:
**Save** crashes (index out of range) before showing the "Saved" confirmation.

LoopBack catches it via the **simulator log / crash report** and **verify-after-act**.

## Build + run on the Simulator (inside the macOS VM)
```bash
brew install xcodegen          # if not present
xcodegen generate              # -> SampleBuggyApp.xcodeproj
xcodebuild -scheme SampleBuggyApp -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
# artifact: build/Build/Products/Debug-iphonesimulator/SampleBuggyApp.app
xcrun simctl install booted build/Build/Products/Debug-iphonesimulator/SampleBuggyApp.app
xcrun simctl launch booted com.loopback.SampleBuggyApp
```
Driven by `loopback/adapters/ios.py` (task #10). See
[`../../infra/macos-tart/`](../../infra/macos-tart/).
