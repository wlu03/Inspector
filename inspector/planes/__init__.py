"""Execution planes — the VMs each surface runs inside.

Two planes (iOS cannot share the Linux one — the Simulator requires macOS):
  - LinuxPlane  (E2B Desktop microVM): web, Electron, Android (Redroid)
  - MacOSPlane  (tart macOS VM on Apple silicon): iOS (Xcode Simulator + idb)

See infra/ for how each VM is provisioned.
"""

from .base import ExecutionPlane
from .linux import LinuxPlane
from .macos import MacOSPlane

__all__ = ["ExecutionPlane", "LinuxPlane", "MacOSPlane"]
