#!/usr/bin/env bash
# Run INSIDE the tart macOS VM to install iOS Simulator runtime + idb.
# Usage: ssh admin@<vm-ip> 'bash /tmp/provision-vm.sh'
set -euo pipefail

echo "=== Inspector iOS VM provisioner ==="

# --- iOS Simulator runtime (~7GB) ---
echo ""
echo "[1/4] Checking iOS Simulator runtime ..."
if xcrun simctl list runtimes 2>/dev/null | grep -q "iOS"; then
  echo "  iOS runtime already installed."
else
  echo "  Downloading iOS Simulator runtime (~7GB, this takes a while) ..."
  xcodebuild -downloadPlatform iOS
  echo "  iOS runtime installed."
fi

# --- idb (Facebook's iOS Development Bridge) ---
echo ""
echo "[2/4] Installing idb-companion ..."
if command -v idb_companion &>/dev/null; then
  echo "  idb-companion already installed."
else
  brew install idb-companion
fi

echo ""
echo "[3/4] Installing fb-idb (Python client) ..."
if python3 -c "import idb" &>/dev/null 2>&1; then
  echo "  fb-idb already installed."
else
  pip3 install fb-idb
fi

# --- xcodegen (for building sample-buggy-ios) ---
echo ""
echo "[4/4] Installing xcodegen ..."
if command -v xcodegen &>/dev/null; then
  echo "  xcodegen already installed."
else
  brew install xcodegen
fi

# --- verify ---
echo ""
echo "=== Verification ==="
echo -n "Xcode:          "; xcodebuild -version | head -1
echo -n "simctl:         "; xcrun simctl list runtimes | grep iOS | head -1 || echo "MISSING"
echo -n "idb_companion:  "; idb_companion --version 2>/dev/null || echo "MISSING"
echo -n "idb:            "; idb --help 2>/dev/null | head -1 || echo "MISSING"
echo -n "xcodegen:       "; xcodegen --version 2>/dev/null || echo "MISSING"

# --- boot a simulator ---
echo ""
echo "=== Booting a simulator ==="
UDID=""
# Try to find an existing iPhone simulator
UDID=$(xcrun simctl list devices available --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for rt, devs in data.get('devices', {}).items():
    if 'iOS' not in rt: continue
    for d in devs:
        if 'iPhone' in d.get('name', ''):
            print(d['udid'])
            sys.exit(0)
" 2>/dev/null || true)

if [[ -z "$UDID" ]]; then
  echo "Creating an iPhone 15 simulator ..."
  UDID=$(xcrun simctl create 'Inspector iPhone' \
    'com.apple.CoreSimulator.SimDeviceType.iPhone-15' 2>/dev/null || true)
fi

if [[ -n "$UDID" ]]; then
  echo "  Simulator UDID: $UDID"
  xcrun simctl boot "$UDID" 2>/dev/null || true
  echo "  Simulator booted."
else
  echo "  WARNING: Could not find or create a simulator."
fi

echo ""
echo "=== Provisioning complete ==="
echo "The VM is ready for Inspector's iOS adapter."
