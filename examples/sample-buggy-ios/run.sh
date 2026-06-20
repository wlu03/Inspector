#!/usr/bin/env bash
# One-command launch for the sample-buggy-ios fixture.
# Generates the project, builds for the simulator, installs, and launches.
# Requires: Xcode (with an iOS simulator runtime) + xcodegen (`brew install xcodegen`).
set -euo pipefail
cd "$(dirname "$0")"

BUNDLE_ID="com.inspector.SampleBuggyApp"
APP="build/Build/Products/Debug-iphonesimulator/SampleBuggyApp.app"

xcodegen generate

xcodebuild -scheme SampleBuggyApp -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build

# Boot the first available simulator (no-op if one is already booted).
xcrun simctl boot booted 2>/dev/null || xcrun simctl boot "iPhone 15" 2>/dev/null || true
open -a Simulator || true

xcrun simctl install booted "$APP"
echo "Launching $BUNDLE_ID — tap Save to trigger the planted crash."
xcrun simctl launch --console booted "$BUNDLE_ID"
