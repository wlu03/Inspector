#!/usr/bin/env bash
# Load the Android kernel modules Redroid needs. Run on the LINUX HOST as root.
# Works on a host whose kernel ships binder/ashmem (most Ubuntu). NOT on
# managed/serverless containers, macOS Docker, or WSL2.
set -euo pipefail

apt-get update && apt-get install -y "linux-modules-extra-$(uname -r)" || true

modprobe binder_linux devices="binder,hwbinder,vndbinder" || \
  echo "WARN: binder_linux not available for kernel $(uname -r) — build from remote-android/redroid-modules"
modprobe ashmem_linux || echo "note: ashmem missing — modern kernels use memfd, usually fine"

# persist across reboots
echo "binder_linux"  | tee /etc/modules-load.d/binder.conf  >/dev/null
echo "ashmem_linux"  | tee /etc/modules-load.d/ashmem.conf  >/dev/null

echo "OK. Next: docker compose up -d && adb connect localhost:5555"
