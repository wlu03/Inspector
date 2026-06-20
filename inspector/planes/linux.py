from __future__ import annotations

from ..config import Config
from ..sandbox import E2BSandbox
from .base import ExecutionPlane


class LinuxPlane(ExecutionPlane):
    """Linux microVM (E2B Desktop). Hosts web, Electron, and Android (Redroid).

    Thin wrapper over the existing `E2BSandbox` so the web/Electron adapters can
    migrate onto the plane abstraction with no behavior change. The Android
    surface runs a Redroid container *inside* this plane (see planes/android.py
    and infra/android-redroid/).
    """

    name = "linux-e2b"

    def __init__(self, config: Config):
        self.config = config
        self.sandbox = E2BSandbox(config)

    def start(self) -> None:
        self.sandbox.start()

    def run_sync(self, cmd: str, timeout: int = 60):
        return self.sandbox.run_sync(cmd, timeout)

    def run_bg(self, cmd: str):
        return self.sandbox.run_bg(cmd)

    def upload(self, local_path: str, remote_path: str = "/home/user/app") -> None:
        self.sandbox.upload_dir(local_path, remote_path)

    def screenshot(self) -> bytes:
        return self.sandbox.screenshot()

    def stop(self) -> None:
        self.sandbox.kill()
