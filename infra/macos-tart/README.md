# iOS plane — macOS VM via tart

The **only** way to run iOS in a VM is a macOS VM (Apple-silicon host) or Corellium.
This plane uses [tart](https://tart.run) — open-source macOS/Linux VMs on Apple
silicon, designed for CI.

## Prerequisites
- An **Apple-silicon** machine to host the VM (yours, a Mac mini, or a cloud
  Apple-silicon host). Apple licensing allows **max 2 macOS VMs per host**.
- `brew install cirruslabs/cli/tart`

## Quick start

```bash
# 1. Clone + boot the macOS VM (one-time ~60GB download)
./setup.sh

# 2. Provision the VM (install iOS runtime + idb + xcodegen)
scp -o StrictHostKeyChecking=no provision-vm.sh admin@<vm-ip>:/tmp/
ssh admin@<vm-ip> 'bash /tmp/provision-vm.sh'

# 3. Set the env var and run the demo
export INSPECTOR_MACOS_HOST=<vm-ip>
python scripts/demo_ios.py
```

## Scripts

| Script | What it does |
|---|---|
| `setup.sh` | Clones the base image, boots the VM headless, waits for SSH, prints the IP |
| `provision-vm.sh` | Run inside the VM — installs iOS Simulator runtime, idb, xcodegen |
| `status.sh` | Health check — VM state, SSH, Xcode, runtimes, simulators |

## How it works

```
Your Mac (host)
  │
  ├── tart run --no-graphics inspector-ios
  │     └── macOS VM (guest)
  │           ├── Xcode + iOS Simulator
  │           ├── idb (input: tap/type/swipe)
  │           └── simctl (boot/install/launch/screenshot/logs)
  │
  ├── Inspector MCP server
  │     ├── MacOSPlane (SSH into the VM)
  │     └── IOSAdapter (simctl + idb commands)
  │
  └── Claude Code / Cursor (MCP client)
        └── launch_app → observe → act → verify → stop
```

## Drive it manually (what the iOS adapter does over SSH)
```bash
ssh admin@<vm-ip>
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
- `scripts/demo_ios.py` — end-to-end demo script
- Sample app: [`../../examples/sample-buggy-ios/`](../../examples/sample-buggy-ios/)

## VM lifecycle
```bash
tart run --no-graphics inspector-ios &   # boot
tart ip inspector-ios                    # get IP
tart stop inspector-ios                  # stop
tart delete inspector-ios                # remove (frees ~60GB)
```

## Note
The iOS Simulator is a macOS process against iOS frameworks; it is **not** a real
device. For real-iOS fidelity (jailbreak/root/device behavior) use Corellium
([../ios-corellium/](../ios-corellium/)).
