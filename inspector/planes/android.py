from __future__ import annotations

import itertools
import os
import subprocess
import time

from .linux import LinuxPlane

# Even console ports (5554, 5556, …) handed out one-per-emulator so parallel instances
# don't collide. adb claims port+1, hence the step of 2.
_emu_port_seq = itertools.count(5554, 2)

# --- local Android Emulator (AVD) — the default, runs on THIS machine ---

# Where the Android SDK lives (ANDROID_HOME / the macOS default).
def _sdk_root() -> str:
    return (
        os.environ.get("ANDROID_HOME")
        or os.environ.get("ANDROID_SDK_ROOT")
        or os.path.expanduser("~/Library/Android/sdk")
    )


def _sdk_bin(*parts: str) -> str:
    """Absolute path to an SDK tool, falling back to bare name (PATH lookup)."""
    path = os.path.join(_sdk_root(), *parts)
    return path if os.path.exists(path) else parts[-1]


def emulator_argv(emulator_bin: str, avd: str, port: int = 5554,
                  headless: bool = True, read_only: bool = True) -> list[str]:
    """Args to boot an ephemeral AVD with adb on a fixed port. Pure.

    headless=True adds `-no-window` so NO emulator window appears (screencap still
    works — the framebuffer is rendered regardless). Set INSPECTOR_SHOW_EMULATOR=1 to
    watch it instead. read_only=True lets MULTIPLE emulators boot from one AVD at once
    (the parallel/multi-agent fan-out) with a fresh ephemeral data partition each.
    """
    argv = [
        emulator_bin, "-avd", avd, "-port", str(port),
        "-no-snapshot-save", "-no-boot-anim", "-no-audio",
        "-gpu", "swiftshader_indirect",   # software GL — works headless on any Mac
    ]
    if read_only:
        argv.append("-read-only")         # share one AVD across parallel instances
    if headless:
        argv.append("-no-window")
    return argv


def parse_avd_list(out: str) -> list[str]:
    """AVD names from `emulator -list-avds` (skips warning lines). Pure."""
    avds = []
    for line in (out or "").splitlines():
        line = line.strip()
        if line and " " not in line and not line.startswith(("INFO", "WARNING", "PANIC")):
            avds.append(line)
    return avds


class LocalEmulatorRuntime:
    """Android Emulator (AVD) running locally — no remote host, no Redroid, no kernel
    modules. Apple Silicon runs arm64 system images natively (Hypervisor.framework).

    Driven over the SAME adb interface as Redroid, so AndroidAdapter is unchanged —
    only this runtime differs. `emulator_argv`/`parse_avd_list` are pure (unit-tested);
    `start`/`stop` shell out to the local SDK.
    """

    def __init__(self, config, avd: str | None = None, port: int | None = None):
        self.config = config
        self.avd = avd or getattr(config, "android_avd", None)
        # Even console ports, unique per instance (adb uses port+1), so multiple
        # emulators coexist in a parallel/multi-agent run instead of colliding on 5554.
        self.port = port if port is not None else next(_emu_port_seq)
        self.serial = f"emulator-{self.port}"
        self._proc: subprocess.Popen | None = None

    def start(self) -> str:
        avd = self.avd or self._first_avd()
        if not avd:
            raise RuntimeError(
                "no AVD found — create one: `sdkmanager 'system-images;android-34;google_apis;arm64-v8a'` "
                "then `avdmanager create avd -n inspector -k '...'` (see runbook)"
            )
        headless = os.environ.get("INSPECTOR_SHOW_EMULATOR") != "1"  # default: no window
        self._proc = subprocess.Popen(
            emulator_argv(_sdk_bin("emulator", "emulator"), avd, self.port, headless=headless),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._wait_boot()
        return self.serial

    def stop(self) -> None:
        adb = _sdk_bin("platform-tools", "adb")
        try:
            subprocess.run([adb, "-s", self.serial, "emu", "kill"], timeout=15)
        except Exception:
            pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # --- helpers ---
    def _first_avd(self) -> str | None:
        out = subprocess.run(
            [_sdk_bin("emulator", "emulator"), "-list-avds"], capture_output=True, text=True
        ).stdout
        avds = parse_avd_list(out)
        return avds[0] if avds else None

    def _wait_boot(self, timeout: int = 180) -> None:
        adb = _sdk_bin("platform-tools", "adb")
        subprocess.run([adb, "-s", self.serial, "wait-for-device"], timeout=timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(
                [adb, "-s", self.serial, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True,
            )
            if r.stdout.strip() == "1":
                return
            time.sleep(2)
        raise TimeoutError("emulator did not finish booting")


class RedroidRuntime:
    """Android-in-a-container (Redroid), run INSIDE the Linux plane's host.

    Redroid boots the Android userspace on the host kernel (no nested-virt), so
    it lives on the same Linux plane as web/Electron — but it needs `binder`/
    `ashmem` kernel modules loaded on the host (see infra/android-redroid/).

    SCAFFOLD — implementation steps:
      start():     `docker run -d --privileged -p 5555:5555 redroid/redroid:...`
                   then `adb connect <host>:5555` ; `adb wait-for-device`
      install():   `adb -s <serial> install -r -t app.apk`
      launch():    `adb -s <serial> shell am start -n <pkg>/.MainActivity`
      screenshot:  `adb -s <serial> exec-out screencap -p`
      input:       `adb -s <serial> shell input tap|text|swipe|keyevent`
      logs:        `adb -s <serial> logcat -b crash -d`
    The AndroidAdapter (inspector/adapters/android.py) drives this — it does NOT
    use the Linux plane's desktop screenshot.
    """

    def __init__(self, plane: LinuxPlane, serial: str = "localhost:5555"):
        self.plane = plane
        self.serial = serial

    def start(self) -> None:
        raise NotImplementedError(
            "RedroidRuntime.start — docker run + adb connect (see infra/android-redroid/README.md)"
        )
