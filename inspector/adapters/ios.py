from __future__ import annotations

from ..config import Config
from ..models import Surface
from .base import InputAction, SurfaceAdapter


class IOSAdapter(SurfaceAdapter):
    """iOS via the Simulator on a macOS host (simctl + idb). See docs/11 Part K.

    Skeleton — the M3 milestone, and the only adapter that requires macOS.
    Implementation outline:
      - host: Xcode + command line tools (macOS only)
      - boot: `xcrun simctl boot <UDID>`; `simctl bootstatus <UDID> -b`
      - build for simulator: `xcodebuild -sdk iphonesimulator CODE_SIGNING_ALLOWED=NO`
        or `npx expo run:ios`
      - install/launch: `simctl install booted MyApp.app`; `simctl launch --console-pty ...`
      - screenshot: `simctl io booted screenshot`
      - input: `idb ui tap|swipe|text|key`; a11y tree via `idb ui describe-all`
      - logs: `simctl spawn booted log stream`; crashes at ~/Library/Logs/DiagnosticReports/
    """

    surface = Surface.IOS

    def __init__(self, config: Config):
        self.config = config
        self.udid: str | None = None
        self.bundle_id: str | None = None

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        raise NotImplementedError("IOSAdapter.launch — simctl/idb wiring, macOS only (docs/11 Part K)")

    def is_ready(self) -> bool:
        raise NotImplementedError("IOSAdapter.is_ready (docs/11 Part K)")

    def screenshot(self) -> bytes:
        raise NotImplementedError("IOSAdapter.screenshot — simctl io screenshot (docs/11 Part K)")

    def input(self, action: InputAction) -> None:
        raise NotImplementedError("IOSAdapter.input — idb ui tap/text (docs/11 Part K)")

    def logs(self) -> list[str]:
        raise NotImplementedError("IOSAdapter.logs — simctl log stream (docs/11 Part K)")

    def rendered_elements(self) -> list[str]:
        # Same oracle contract as web/Android — the source is the accessibility tree:
        # `idb ui describe-all` → collect each element's AXLabel / identifier. Wired
        # with the rest of M3.
        raise NotImplementedError(
            "IOSAdapter.rendered_elements — idb ui describe-all (docs/11 Part K)"
        )

    def screen_size(self) -> tuple[int, int]:
        raise NotImplementedError("IOSAdapter.screen_size (docs/11 Part K)")

    def teardown(self) -> None:
        # simctl shutdown <UDID>
        pass
