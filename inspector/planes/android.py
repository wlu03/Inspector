from __future__ import annotations

from .linux import LinuxPlane


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
