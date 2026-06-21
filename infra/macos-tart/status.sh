#!/usr/bin/env bash
# Quick status check for the Inspector iOS VM.
set -euo pipefail

VM="inspector-ios"

echo "=== Inspector iOS VM status ==="
echo ""

# tart
if ! command -v tart &>/dev/null; then
  echo "tart: NOT INSTALLED"
  exit 1
fi
echo "tart: $(tart --version)"

# VM exists?
if tart list 2>/dev/null | grep -q "$VM"; then
  echo "VM '$VM': exists"
else
  echo "VM '$VM': NOT FOUND (run ./setup.sh to create)"
  exit 0
fi

# VM IP (running?)
IP="$(tart ip "$VM" 2>/dev/null || true)"
if [[ -n "$IP" ]]; then
  echo "VM state: RUNNING"
  echo "VM IP: $IP"
else
  echo "VM state: STOPPED"
  echo ""
  echo "Start with: tart run --no-graphics $VM &"
  exit 0
fi

# SSH check
echo ""
echo "=== VM health (over SSH) ==="
if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       -o ConnectTimeout=5 -o LogLevel=ERROR \
       admin@"$IP" "echo ok" &>/dev/null; then
  echo "SSH: OK"
else
  echo "SSH: UNREACHABLE"
  exit 1
fi

# Xcode
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    admin@"$IP" "
echo -n 'Xcode: '; xcodebuild -version 2>/dev/null | head -1 || echo 'MISSING'
echo -n 'iOS runtime: '; xcrun simctl list runtimes 2>/dev/null | grep iOS | head -1 || echo 'MISSING'
echo -n 'idb_companion: '; command -v idb_companion &>/dev/null && echo 'installed' || echo 'MISSING'
echo -n 'idb: '; command -v idb &>/dev/null && echo 'installed' || echo 'MISSING'
echo -n 'xcodegen: '; command -v xcodegen &>/dev/null && echo 'installed' || echo 'MISSING'
echo ''
echo 'Simulators:'
xcrun simctl list devices available 2>/dev/null | grep -E '(iPhone|iPad)' | head -5 || echo '  none'
"
