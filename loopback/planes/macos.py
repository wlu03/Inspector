from __future__ import annotations

from .base import ExecutionPlane


class MacOSPlane(ExecutionPlane):
    """macOS VM (tart, on Apple silicon) — the ONLY way to run iOS in a VM.

    Boots a macOS guest that has Xcode + idb, then runs `simctl`/`idb` over SSH.
    Apple licensing: macOS VMs run only on Apple hardware, max 2 per host.
    Corellium (infra/ios-corellium/) is the alternative iOS plane.

    SCAFFOLD — implementation steps (see infra/macos-tart/README.md):
      start():   `tart clone <base-image> loopback-ios`
                 `tart run --no-graphics loopback-ios &` ; `tart ip loopback-ios`
      run_sync/run_bg: ssh admin@<ip> '<cmd>'
      upload():  scp into the guest
      screenshot(): `xcrun simctl io booted screenshot -` over SSH
      stop():    `tart stop loopback-ios` (+ optional `tart delete`)
    The iOS adapter (loopback/adapters/ios.py) issues all simctl/idb here.
    """

    name = "macos-tart"
    VM_NAME = "loopback-ios"

    def __init__(
        self,
        base_image: str = "ghcr.io/cirruslabs/macos-sequoia-xcode:latest",
        host: str | None = None,  # guest IP once booted, or a remote macOS host
        user: str = "admin",
    ):
        self.base_image = base_image
        self.host = host
        self.user = user

    def start(self) -> None:
        raise NotImplementedError(
            "MacOSPlane.start: tart clone+run+ip — see infra/macos-tart/README.md"
        )

    def run_sync(self, cmd: str, timeout: int = 60):
        # subprocess.run(["ssh", f"{self.user}@{self.host}", cmd], capture_output=True, text=True, timeout=timeout)
        raise NotImplementedError("MacOSPlane.run_sync: ssh into the macOS VM")

    def run_bg(self, cmd: str):
        raise NotImplementedError("MacOSPlane.run_bg: ssh background command")

    def upload(self, local_path: str, remote_path: str) -> None:
        raise NotImplementedError("MacOSPlane.upload: scp into the macOS VM")

    def screenshot(self) -> bytes:
        raise NotImplementedError("MacOSPlane.screenshot: simctl io booted screenshot")

    def stop(self) -> None:
        raise NotImplementedError("MacOSPlane.stop: tart stop/delete")
