from __future__ import annotations

import time

from .linux import LinuxPlane


class RedroidRuntime:
    """Android-in-a-container (Redroid), run INSIDE the Linux plane's E2B sandbox.

    Redroid boots the Android userspace on the host kernel (no nested-virt), so
    it lives on the same Linux plane as web/Electron — but it needs `binder`/
    `ashmem` kernel modules loaded on the host (see infra/android-redroid/).

    All commands (docker, adb) are run inside the E2B sandbox via the LinuxPlane.
    """

    REDROID_IMAGE = "redroid/redroid:12.0.0_64only-latest"
    CONTAINER_NAME = "inspector-redroid"

    def __init__(
        self,
        plane: LinuxPlane,
        serial: str = "localhost:5555",
        width: int = 1080,
        height: int = 1920,
        dpi: int = 420,
    ):
        self.plane = plane
        self.serial = serial
        self.width = width
        self.height = height
        self.dpi = dpi

    def start(self) -> None:
        """Load kernel modules, start Redroid container, connect adb."""
        # Load binder/ashmem modules (may already be loaded)
        self.plane.run_sync(
            "modprobe binder_linux devices='binder,hwbinder,vndbinder' 2>/dev/null || true",
            timeout=15,
        )
        self.plane.run_sync("modprobe ashmem_linux 2>/dev/null || true", timeout=15)

        # Stop any existing container
        self.plane.run_sync(
            f"docker rm -f {self.CONTAINER_NAME} 2>/dev/null || true", timeout=15,
        )

        # Start Redroid
        self.plane.run_sync(
            f"docker run -d --privileged --name {self.CONTAINER_NAME} "
            f"-p 5555:5555 "
            f"{self.REDROID_IMAGE} "
            f"androidboot.redroid_width={self.width} "
            f"androidboot.redroid_height={self.height} "
            f"androidboot.redroid_dpi={self.dpi} "
            f"androidboot.redroid_gpu_mode=guest",
            timeout=120,
        )

        # Wait for the container to be healthy, then connect adb
        time.sleep(10)
        self._connect_adb()

    def _connect_adb(self, timeout: int = 60) -> None:
        """Connect adb and wait for the device to be ready."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            res = self.plane.run_sync(
                f"adb connect {self.serial} 2>&1", timeout=10,
            )
            stdout = res.stdout if res and getattr(res, "stdout", "") else ""
            if "connected" in stdout:
                break
            time.sleep(3)

        # Wait for device to be fully booted
        self.plane.run_sync(
            f"adb -s {self.serial} wait-for-device", timeout=60,
        )
        # Wait for boot_completed
        deadline = time.time() + 60
        while time.time() < deadline:
            res = self.plane.run_sync(
                f"adb -s {self.serial} shell getprop sys.boot_completed 2>/dev/null",
                timeout=10,
            )
            stdout = res.stdout.strip() if res and getattr(res, "stdout", "") else ""
            if stdout == "1":
                return
            time.sleep(3)

    def adb(self, cmd: str, timeout: int = 30) -> str:
        """Run an adb command and return stdout."""
        res = self.plane.run_sync(
            f"adb -s {self.serial} {cmd}", timeout=timeout,
        )
        return res.stdout if res and getattr(res, "stdout", "") else ""

    def install(self, apk_path: str) -> None:
        self.adb(f"install -r -t {apk_path}", timeout=120)

    def launch(self, package: str, activity: str | None = None) -> None:
        if activity:
            self.adb(f"shell am start -n {package}/{activity}")
        else:
            # Resolve the main activity
            res = self.adb(f"shell cmd package resolve-activity --brief {package}")
            lines = res.strip().splitlines()
            if len(lines) >= 2:
                component = lines[-1]  # e.g. com.example/.MainActivity
                self.adb(f"shell am start -n {component}")
            else:
                self.adb(f"shell monkey -p {package} -c android.intent.category.LAUNCHER 1")

    def screenshot(self) -> bytes:
        """Capture the screen as PNG bytes."""
        res = self.plane.run_sync(
            f"adb -s {self.serial} exec-out screencap -p", timeout=15,
        )
        # exec-out returns raw bytes; run_sync may return a CommandResult
        if hasattr(res, "stdout") and isinstance(res.stdout, bytes):
            return res.stdout
        # If stdout is text, the sandbox may have mangled binary — fall back to file
        self.plane.run_sync(
            f"adb -s {self.serial} exec-out screencap -p > /tmp/screen.png", timeout=15,
        )
        res = self.plane.run_sync("cat /tmp/screen.png", timeout=10)
        if hasattr(res, "stdout") and isinstance(res.stdout, bytes):
            return res.stdout
        # Last resort: use the sandbox's own screenshot (full desktop)
        return self.plane.screenshot()

    def tap(self, x: int, y: int) -> None:
        self.adb(f"shell input tap {x} {y}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.adb(f"shell input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def text(self, s: str) -> None:
        # adb input text uses %s for spaces
        escaped = s.replace(" ", "%s").replace("'", "\\'")
        self.adb(f'shell input text "{escaped}"')

    def keyevent(self, code: int | str) -> None:
        self.adb(f"shell input keyevent {code}")

    def logcat_crash(self) -> str:
        """Dump crash logs."""
        return self.adb("logcat -b crash -d", timeout=10)

    def logcat_clear(self) -> None:
        self.adb("logcat -c", timeout=10)

    def pid_of(self, package: str) -> str | None:
        """Return PID of the package, or None if not running (= crashed)."""
        res = self.adb(f"shell pidof -s {package}", timeout=5)
        pid = res.strip()
        return pid if pid else None

    def force_stop(self, package: str) -> None:
        self.adb(f"shell am force-stop {package}")

    def stop(self) -> None:
        """Stop the Redroid container and disconnect adb."""
        self.plane.run_sync(
            f"adb disconnect {self.serial} 2>/dev/null || true", timeout=10,
        )
        self.plane.run_sync(
            f"docker rm -f {self.CONTAINER_NAME} 2>/dev/null || true", timeout=15,
        )
