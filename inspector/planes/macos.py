from __future__ import annotations

import base64
import subprocess
import time
from dataclasses import dataclass

from .base import ExecutionPlane

_SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=10",
    "-o", "LogLevel=ERROR",
]


@dataclass
class RunResult:
    """Mirrors E2BSandbox's result shape so adapters read `.stdout` uniformly."""

    stdout: str
    stderr: str
    exit_code: int


def ssh_argv(user: str, host: str, cmd: str, ssh_key: str | None = None) -> list[str]:
    """SSH argv for one remote command. Pure (unit-tested)."""
    key = ["-i", ssh_key] if ssh_key else []
    return ["ssh", *_SSH_OPTS, *key, f"{user}@{host}", cmd]


def scp_argv(user: str, host: str, local: str, remote: str, ssh_key: str | None = None) -> list[str]:
    """SCP argv for a recursive upload. Pure (unit-tested)."""
    key = ["-i", ssh_key] if ssh_key else []
    return ["scp", "-r", *_SSH_OPTS, *key, local, f"{user}@{host}:{remote}"]


def decode_screenshot(b64_stdout: str) -> bytes:
    """Decode a base64'd PNG captured over SSH. Pure (unit-tested).

    The screenshot is base64'd on the guest because a raw PNG through an ssh pipe
    gets mangled. Returns b"" on bad input rather than raising.
    """
    try:
        return base64.b64decode((b64_stdout or "").strip())
    except Exception:
        return b""


class MacOSPlane(ExecutionPlane):
    """macOS VM (tart, on Apple silicon) — the ONLY way to run iOS in a VM.

    Boots a macOS guest with Xcode + idb, then runs `simctl`/`idb` over SSH. If
    `host` is set, connects to an already-running Mac/guest and skips tart entirely
    (dev: point at localhost). Apple licensing caps macOS VMs at 2 per host.

    Mirrors E2BSandbox's method surface (run_sync/run_bg/upload/screenshot/stop) so
    IOSAdapter reads like DesktopAdapter. The iOS adapter issues all simctl/idb here.
    """

    name = "macos-tart"
    VM_NAME = "inspector-ios"

    def __init__(
        self,
        base_image: str = "ghcr.io/cirruslabs/macos-sequoia-xcode:latest",
        host: str | None = None,
        user: str = "admin",
        ssh_key: str | None = None,
        local: bool = False,
    ):
        self.base_image = base_image
        self.host = host          # if set: connect directly, skip tart
        self.user = user
        self.ssh_key = ssh_key
        self.local = local        # run simctl/idb on THIS host via subprocess (no VM/SSH)
        self._owns_vm = (not local) and host is None  # a VM we cloned and must stop
        self._vm_proc: subprocess.Popen | None = None
        self._bg: list[subprocess.Popen] = []

    # --- lifecycle ---
    def start(self) -> None:
        if self.local or self.host:  # local host, or an already-running Mac/guest
            return
        subprocess.run(["tart", "clone", self.base_image, self.VM_NAME], check=True, timeout=900)
        # `tart run` is foreground/blocking — background it.
        self._vm_proc = subprocess.Popen(["tart", "run", "--no-graphics", self.VM_NAME])
        self.host = self._wait_ip()
        # keep the auto-login Aqua session awake so simctl-over-SSH isn't blank
        self.run_bg("caffeinate -dimsu")

    def _wait_ip(self, timeout: int = 180) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(["tart", "ip", self.VM_NAME], capture_output=True, text=True)
            ip = (r.stdout or "").strip()
            if ip:
                return ip
            time.sleep(2)
        raise RuntimeError("tart ip timed out — VM never reported an IP")

    def _argv(self, cmd: str) -> list[str]:
        """Local: a host shell; VM: ssh into the guest."""
        if self.local:
            return ["/bin/bash", "-lc", cmd]
        return ssh_argv(self.user, self.host, cmd, self.ssh_key)

    # --- command execution ---
    def run_sync(self, cmd: str, timeout: int = 120) -> RunResult | None:
        if not self.local and not self.host:
            return None
        try:
            r = subprocess.run(self._argv(cmd), capture_output=True, text=True, timeout=timeout)
            return RunResult(r.stdout, r.stderr, r.returncode)
        except Exception:
            return None  # mirror E2BSandbox: never raise out of a command

    def run_bg(self, cmd: str) -> subprocess.Popen | None:
        if not self.local and not self.host:
            return None
        try:
            p = subprocess.Popen(self._argv(cmd))
            self._bg.append(p)
            return p
        except Exception:
            return None

    def upload(self, local_path: str, remote_path: str) -> None:
        if self.local:
            return  # the app already lives on this host — nothing to upload
        if not self.host:
            return
        self.run_sync(f"mkdir -p {remote_path}", timeout=30)
        subprocess.run(
            scp_argv(self.user, self.host, local_path, remote_path, self.ssh_key),
            capture_output=True, timeout=900,
        )

    def screenshot(self) -> bytes:
        """PNG of the booted simulator. simctl writes to a file (its `-` stdout mode
        returns nothing), so capture to a temp file then base64 it (binary through an
        ssh/subprocess pipe corrupts)."""
        path = "/tmp/inspector_ios_shot.png"
        r = self.run_sync(
            f"xcrun simctl io booted screenshot {path} >/dev/null 2>&1 && base64 -i {path}",
            timeout=60,
        )
        if r is None:
            return b""
        return decode_screenshot(r.stdout)

    def stop(self) -> None:
        for p in self._bg:
            try:
                p.terminate()
            except Exception:
                pass
        self._bg.clear()
        if self._owns_vm:
            subprocess.run(["tart", "stop", self.VM_NAME], capture_output=True)
            subprocess.run(["tart", "delete", self.VM_NAME], capture_output=True)
        if self._vm_proc is not None:
            try:
                self._vm_proc.terminate()
            except Exception:
                pass
            self._vm_proc = None
