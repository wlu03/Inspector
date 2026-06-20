from __future__ import annotations

from abc import ABC, abstractmethod


class ExecutionPlane(ABC):
    """A provisioned VM that one or more SurfaceAdapters run inside.

    The plane owns VM lifecycle + command execution; the adapter layers the
    surface-specific logic (browser/Electron/adb/simctl) on top. This is the
    seam that keeps everything "in a VM" rather than on the host machine.
    """

    name: str

    @abstractmethod
    def start(self) -> None:
        """Provision/boot the VM."""

    @abstractmethod
    def run_sync(self, cmd: str, timeout: int = 60):
        """Run a command in the VM and return its result (stdout/exit_code)."""

    @abstractmethod
    def run_bg(self, cmd: str):
        """Start a long-running command in the VM (returns a handle)."""

    @abstractmethod
    def upload(self, local_path: str, remote_path: str) -> None:
        """Copy a local file/dir into the VM."""

    @abstractmethod
    def screenshot(self) -> bytes:
        """Capture the VM's screen as PNG bytes."""

    @abstractmethod
    def stop(self) -> None:
        """Tear down the VM."""
