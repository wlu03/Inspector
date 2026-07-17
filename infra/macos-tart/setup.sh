#!/usr/bin/env bash
# Provision a macOS VM with Xcode for the Inspector iOS surface.
# Requires: Apple-silicon host + `tart` (brew install cirruslabs/cli/tart).
set -euo pipefail

VM="inspector-ios"
BASE="ghcr.io/cirruslabs/macos-sequoia-xcode:latest"

# --- preflight ---
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "ERROR: Tart requires an Apple-silicon (arm64) host." >&2
  exit 1
fi

if ! command -v tart &>/dev/null; then
  echo "ERROR: tart not found. Install with: brew install cirruslabs/cli/tart" >&2
  exit 1
fi

# --- clone (one-time, ~60GB) ---
if ! tart list | grep -q "$VM"; then
  echo "Cloning $BASE -> $VM (large download, one-time) ..."
  tart clone "$BASE" "$VM"
  echo "Clone complete."
else
  echo "VM '$VM' already exists, skipping clone."
fi

# --- boot ---
echo "Booting $VM (headless) ..."
tart run --no-graphics "$VM" >/dev/null 2>&1 &
TART_PID=$!
echo "tart run PID: $TART_PID"

# --- wait for IP ---
echo "Waiting for VM to get an IP ..."
IP=""
for i in $(seq 1 40); do
  IP="$(tart ip "$VM" 2>/dev/null || true)"
  if [[ -n "$IP" ]]; then
    break
  fi
  sleep 3
done

if [[ -z "$IP" ]]; then
  echo "ERROR: VM did not get an IP within 120s." >&2
  kill "$TART_PID" 2>/dev/null || true
  exit 1
fi

echo "VM IP: $IP"

# --- wait for SSH ---
echo "Waiting for SSH ..."
for i in $(seq 1 20); do
  if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
         -o ConnectTimeout=5 -o LogLevel=ERROR \
         admin@"$IP" "echo ok" &>/dev/null; then
    echo "SSH is ready."
    break
  fi
  sleep 3
done

# --- print next steps ---
cat <<EOF

=== Inspector iOS VM is running ===
  VM name:  $VM
  IP:       $IP
  SSH:      ssh admin@$IP  (password: admin)
  tart PID: $TART_PID

Next steps — run the provisioner inside the VM:
  scp -o StrictHostKeyChecking=no provision-vm.sh admin@$IP:/tmp/
  ssh admin@$IP 'bash /tmp/provision-vm.sh'

Or manually:
  ssh admin@$IP
  xcodebuild -downloadPlatform iOS
  brew install idb-companion && pip3 install fb-idb

Then set in your .env:
  INSPECTOR_MACOS_HOST=$IP

To stop the VM later:
  tart stop $VM
EOF
