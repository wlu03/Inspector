from __future__ import annotations

from ..config import Config
from ..models import Surface
from .base import InputAction, SurfaceAdapter


class AndroidAdapter(SurfaceAdapter):
    """Android via Redroid + adb (Linux plane). See docs/11 Part J.

    Skeleton — the adb/Redroid wiring is the M2 milestone. Implementation outline:
      - host prep (one-time, not here): modprobe binder_linux / ashmem_linux
      - `docker run --privileged -p 5555:5555 redroid/redroid:...`
      - `adb connect localhost:5555`
      - build APK (gradle / `expo run:android`); `adb install -r -t app.apk`
      - launch: `adb shell am start -n pkg/.MainActivity`
      - screenshot: `adb exec-out screencap -p`
      - input: `adb shell input tap|text|swipe|keyevent`
      - logs: `adb logcat -b crash -d`
    """

    surface = Surface.ANDROID

    def __init__(self, config: Config):
        self.config = config
        self.serial: str | None = None  # e.g. "localhost:5555"
        self.package: str | None = None

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        raise NotImplementedError("AndroidAdapter.launch — Redroid/adb wiring (docs/11 Part J)")

    def is_ready(self) -> bool:
        raise NotImplementedError("AndroidAdapter.is_ready (docs/11 Part J)")

    def screenshot(self) -> bytes:
        raise NotImplementedError("AndroidAdapter.screenshot — adb exec-out screencap (docs/11 Part J)")

    def input(self, action: InputAction) -> None:
        raise NotImplementedError("AndroidAdapter.input — adb shell input (docs/11 Part J)")

    def logs(self) -> list[str]:
        raise NotImplementedError("AndroidAdapter.logs — adb logcat (docs/11 Part J)")

    def rendered_elements(self) -> list[str]:
        # Same oracle contract as web/iOS — only the source differs: the native view
        # hierarchy. `adb exec-out uiautomator dump /dev/tty` → parse the XML for
        # clickable nodes' text/content-desc. Wired with the rest of M2.
        raise NotImplementedError(
            "AndroidAdapter.rendered_elements — uiautomator hierarchy (docs/11 Part J)"
        )

    def screen_size(self) -> tuple[int, int]:
        raise NotImplementedError("AndroidAdapter.screen_size (docs/11 Part J)")

    def teardown(self) -> None:
        # adb disconnect / docker stop the Redroid container
        pass
