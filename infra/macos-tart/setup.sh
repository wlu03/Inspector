#!/usr/bin/env bash
# Provision a macOS VM with Xcode for the LoopBack iOS surface.
# Requires: Apple-silicon host + `tart` (brew install cirruslabs/cli/tart).
set -euo pipefail

VM="loopback-ios"
BASE="ghcr.io/cirruslabs/macos-sequoia-xcode:latest"   # macOS + Xcode preinstalled

if ! tart list | grep -q "$VM"; then
  echo "Cloning $BASE -> $VM (large, one-time) ..."
  tart clone "$BASE" "$VM"
fi

echo "Booting $VM ..."
tart run --no-graphics "$VM" >/dev/null 2>&1 &
sleep 30
IP="$(tart ip "$VM")"
echo "VM IP: $IP  (ssh admin@$IP, password 'admin')"

cat <<EOF

Next, inside the VM:
  ssh admin@$IP
  xcodebuild -downloadPlatform iOS              # iOS Simulator runtime (~7GB)
  brew install idb-companion && pip3 install fb-idb

Then set LOOPBACK_MACOS_HOST=$IP for the iOS adapter.
EOF
