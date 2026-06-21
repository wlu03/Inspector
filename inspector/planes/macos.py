from __future__ import annotations

import subprocess
import shlex
import time

from .base import ExecutionPlane


class _CmdResult:
    """Minimal result object to match the interface callers expect (stdout, returncode)."""

    def __init__(self, stdout: str, returncode: int):
        self.stdout = stdout
        self.returncode = returncode


class MacOSPlane(ExecutionPlane):
    """macOS VM (tart, on Apple silicon) — the ONLY way to run iOS in a VM.

    Boots a macOS guest that has Xcode + idb, then runs `simctl`/`idb` over SSH.
    Apple licensing: macOS VMs run only on Apple hardware, max 2 per host.

    If `host` is provided (an IP or hostname), the plane assumes the VM is already
    running and skips tart clone/run. This lets you point at a pre-provisioned VM
    or a remote macOS machine.
    """

    name = "macos-tart"
    VM_NAME = "inspector-ios"

    def __init__(
        self,
        base_image: str = "ghcr.io/cirruslabs/macos-sequoia-xcode:latest",
        host: str | None = None,
        user: str = "admin",
        password: str = "admin",
    ):
        self.base_image = base_image
        self.host = host
        self.user = user
        self.password = password
        self._tart_started = False
        self._bg_processes: list[subprocess.Popen] = []

    def start(self) -> None:
        if self.host:
            return  # already have a reachable macOS host

        # Clone the base image if we don't have it yet
        ls = subprocess.run(
            ["tart", "list"], capture_output=True, text=True, timeout=30,
        )
        if self.VM_NAME not in ls.stdout:
            subprocess.run(
                ["tart", "clone", self.base_image, self.VM_NAME],
                check=True, timeout=3600,  # large image, one-time
            )

        # Boot headless
        proc = subprocess.Popen(
            ["tart", "run", "--no-graphics", self.VM_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._bg_processes.append(proc)
        self._tart_started = True

        # Wait for the VM to get an IP
        deadline = time.time() + 120
        while time.time() < deadline:
            ip_result = subprocess.run(
                ["tart", "ip", self.VM_NAME],
                capture_output=True, text=True, timeout=10,
            )
            ip = ip_result.stdout.strip()
            if ip and ip_result.returncode == 0:
                self.host = ip
                break
            time.sleep(3)
        else:
            raise TimeoutError(f"tart VM {self.VM_NAME} did not get an IP within 120s")

        # Wait for SSH to become available
        self._wait_ssh(timeout=60)

    def _wait_ssh(self, timeout: int = 60) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.run_sync("echo ok", timeout=10)
                return
            except Exception:
                time.sleep(2)
        raise TimeoutError(f"SSH to {self.host} not available within {timeout}s")

    def _ssh_cmd(self, cmd: str, timeout: int = 60) -> list[str]:
        return [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", f"ConnectTimeout={min(timeout, 30)}",
            f"{self.user}@{self.host}",
            cmd,
        ]

    def run_sync(self, cmd: str, timeout: int = 60) -> _CmdResult:
        result = subprocess.run(
            self._ssh_cmd(cmd, timeout),
            capture_output=True, text=True, timeout=timeout + 5,
        )
        return _CmdResult(stdout=result.stdout, returncode=result.returncode)

    def run_bg(self, cmd: str) -> subprocess.Popen:
        proc = subprocess.Popen(
            self._ssh_cmd(f"nohup {cmd} &"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._bg_processes.append(proc)
        return proc

    def upload(self, local_path: str, remote_path: str) -> None:
        subprocess.run(
            [
                "scp", "-r",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR",
                local_path,
                f"{self.user}@{self.host}:{remote_path}",
            ],
            check=True, timeout=300,
        )

    def screenshot(self) -> bytes:
        result = subprocess.run(
            self._ssh_cmd(
                "xcrun simctl io booted screenshot --type=png -", timeout=30,
            ),
            capture_output=True, timeout=35,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"simctl screenshot failed: {result.stderr.decode(errors='replace')}"
            )
        return result.stdout  # raw PNG bytes piped to stdout

    def stop(self) -> None:
        for proc in self._bg_processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._bg_processes.clear()

        if self._tart_started:
            subprocess.run(
                ["tart", "stop", self.VM_NAME],
                capture_output=True, timeout=30,
            )
            self._tart_started = False
