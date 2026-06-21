from __future__ import annotations

import shlex
import subprocess


class AdbTransport:
    """The Android control primitive — the analog of `E2BSandbox` for the web plane.

    Every device interaction is one `adb` invocation. Runs either locally (Inspector
    co-located with the Redroid host) or over SSH (Inspector remote, adb on the host).
    `build_argv` is pure so command construction is unit-testable with no device.
    """

    def __init__(
        self,
        serial: str = "localhost:5555",
        ssh_host: str | None = None,
        ssh_user: str | None = None,
        ssh_key: str | None = None,
    ):
        self.serial = serial
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key

    # --- pure: build the argv (so tests don't need a device) ---
    def build_argv(self, adb_args: list[str]) -> list[str]:
        adb = ["adb", "-s", self.serial, *adb_args]
        if not self.ssh_host:
            return adb
        target = f"{self.ssh_user}@{self.ssh_host}" if self.ssh_user else self.ssh_host
        ssh = ["ssh", "-o", "BatchMode=yes"]
        if self.ssh_key:
            ssh += ["-i", self.ssh_key]
        # adb runs on the remote host; pass it as one quoted remote command
        ssh += [target, " ".join(shlex.quote(a) for a in adb)]
        return ssh

    # --- side-effecting wrappers ---
    def run(self, adb_args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(self.build_argv(adb_args), capture_output=True, timeout=timeout)

    def shell(self, cmd: str, timeout: int = 60) -> str:
        return self.run(["shell", cmd], timeout).stdout.decode("utf-8", "replace")

    def exec_out(self, cmd: str, timeout: int = 60) -> bytes:
        # exec-out is binary-clean (no shell CRLF translation) — required for screencap
        return self.run(["exec-out", cmd], timeout).stdout

    def install(self, apk_path: str, timeout: int = 240) -> None:
        # -r reinstall keeping data, -t allow test/debug APKs
        self.run(["install", "-r", "-t", apk_path], timeout)

    def wait_for_device(self, timeout: int = 120) -> None:
        self.run(["wait-for-device"], timeout)

    def logcat(self, buffers: str = "crash,main", timeout: int = 30) -> str:
        return self.run(["logcat", "-b", buffers, "-d"], timeout).stdout.decode("utf-8", "replace")
