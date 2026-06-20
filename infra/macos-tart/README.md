# iOS plane — macOS VM via tart

The **only** way to run iOS in a VM is a macOS VM (Apple-silicon host) or Corellium.
This plane uses [tart](https://tart.run) — open-source macOS/Linux VMs on Apple
silicon, designed for CI.

## Prerequisites
- An **Apple-silicon** machine to host the VM (yours, a Mac mini, or a cloud
  Apple-silicon host). Apple licensing allows **max 2 macOS VMs per host**.
- `brew install cirruslabs/cli/tart`

## Provision
```bash
./setup.sh                       # clones a macOS+Xcode image, boots it, prints the IP
```
Then, inside the VM (the cirruslabs images use user `admin` / password `admin`):
```bash
ssh admin@<vm-ip>
xcodebuild -downloadPlatform iOS         # the iOS Simulator runtime (~7GB, on-demand)
brew install idb-companion && pip3 install fb-idb
```

## Drive it (what the iOS adapter does over SSH)
```bash
xcrun simctl boot <UDID>; xcrun simctl bootstatus <UDID> -b
xcrun simctl install booted MyApp.app
xcrun simctl launch --console-pty booted com.inspector.SampleBuggyApp
xcrun simctl io booted screenshot screen.png
idb ui tap 100 200 ; idb ui text "hi" ; idb ui describe-all
xcrun simctl spawn booted log stream --predicate 'processImagePath endswith "SampleBuggyApp"'
```

## Code
- `inspector/planes/macos.py` (`MacOSPlane` — SSH transport into the VM)
- `inspector/adapters/ios.py` (`IOSAdapter`) — task #10
- Sample app: [`../../examples/sample-buggy-ios/`](../../examples/sample-buggy-ios/)

## Note
The iOS Simulator is a macOS process against iOS frameworks; it is **not** a real
device. For real-iOS fidelity (jailbreak/root/device behavior) use Corellium
([../ios-corellium/](../ios-corellium/)).
