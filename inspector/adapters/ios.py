from __future__ import annotations

import json
import os
import time

from ..config import Config
from ..models import ActionType, Surface
from ..planes.macos import MacOSPlane
from .base import InputAction, SurfaceAdapter

BUNDLE_ID = "com.inspector.SampleBuggyApp"
APP_DIR = "/tmp/inspector-app"
CRASH_LOG = "/tmp/inspector_crash.log"


class IOSAdapter(SurfaceAdapter):
    """iOS via the Simulator on a macOS host (simctl + idb). See docs/11 Part K.

    Uses MacOSPlane (tart VM or remote macOS) to run all commands over SSH.
    The flow: boot sim -> build for simulator -> install -> launch -> interact.
    """

    surface = Surface.IOS

    def __init__(self, config: Config):
        self.config = config
        self.plane = MacOSPlane(
            host=os.getenv("LOOPBACK_MACOS_HOST"),
            user=os.getenv("LOOPBACK_MACOS_USER", "admin"),
            password=os.getenv("LOOPBACK_MACOS_PASSWORD", "admin"),
        )
        self.udid: str | None = None
        self.bundle_id: str = BUNDLE_ID
        self._log_offset = 0
        self._log_lines: list[str] = []
        self._screen_w = 393  # iPhone 15 logical
        self._screen_h = 852

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        self.plane.start()

        # Upload the app source into the VM
        self.plane.upload(repo_path, APP_DIR)

        # Find or boot a simulator
        self.udid = self._boot_simulator()

        # Build the app for simulator
        self._build_app(dev_command)

        # Install and launch
        app_path = self._find_app_bundle()
        self.plane.run_sync(f"xcrun simctl install {self.udid} {app_path}", timeout=60)

        # Detect bundle ID from the project if possible
        self.bundle_id = self._detect_bundle_id() or BUNDLE_ID

        self.plane.run_sync(
            f"xcrun simctl launch {self.udid} {self.bundle_id}",
            timeout=30,
        )

        # Clear crash log baseline
        self.plane.run_sync(f": > {CRASH_LOG}")

        # Start log stream in background for crash detection
        app_name = self.bundle_id.split(".")[-1]
        self.plane.run_bg(
            f"xcrun simctl spawn {self.udid} log stream "
            f"--predicate 'processImagePath endswith \"{app_name}\"' "
            f"--level error 2>&1 >> {CRASH_LOG}"
        )

    def is_ready(self, timeout_s: float = 60.0) -> bool:
        """Wait until the app process is running in the simulator."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            res = self.plane.run_sync(
                f"xcrun simctl get_app_container {self.udid} {self.bundle_id} 2>/dev/null",
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                time.sleep(2)  # settle time for the UI
                return True
            time.sleep(1)
        return False

    def screenshot(self) -> bytes:
        return self.plane.screenshot()

    def input(self, action: InputAction) -> None:
        t = action.type
        if t == ActionType.CLICK:
            self._idb(f"ui tap {action.x} {action.y}")
        elif t == ActionType.DOUBLE_CLICK:
            self._idb(f"ui tap {action.x} {action.y}")
            time.sleep(0.05)
            self._idb(f"ui tap {action.x} {action.y}")
        elif t == ActionType.TYPE:
            self._idb(f"ui text {_shell_quote(action.text or '')}")
        elif t == ActionType.KEY:
            # idb uses key codes; map common names
            key = _idb_key(action.key or "")
            self._idb(f"ui key {key}")
        elif t == ActionType.SCROLL:
            # Swipe gesture: swipe from center in the given direction
            cx, cy = self._screen_w // 2, self._screen_h // 2
            dist = 200 * action.amount
            if action.direction == "down":
                self._idb(f"ui swipe {cx} {cy} {cx} {cy - dist}")
            elif action.direction == "up":
                self._idb(f"ui swipe {cx} {cy} {cx} {cy + dist}")
            elif action.direction == "left":
                self._idb(f"ui swipe {cx} {cy} {cx + dist} {cy}")
            elif action.direction == "right":
                self._idb(f"ui swipe {cx} {cy} {cx - dist} {cy}")
        elif t == ActionType.WAIT:
            time.sleep(1)

    def logs(self) -> list[str]:
        res = self.plane.run_sync(f"cat {CRASH_LOG} 2>/dev/null || true", timeout=10)
        text = res.stdout if res.returncode == 0 else ""
        lines = text.splitlines()
        new = lines[self._log_offset:]
        self._log_offset = len(lines)

        # Also check for crash reports
        crash_lines = self._check_crash_reports()
        return new + crash_lines

    def rendered_elements(self) -> list[str]:
        # Same oracle contract as web/Android — the source is the accessibility tree:
        # `idb ui describe-all` → collect each element's AXLabel / identifier. Wired
        # with the rest of M3.
        raise NotImplementedError(
            "IOSAdapter.rendered_elements — idb ui describe-all (docs/11 Part K)"
        )

    def screen_size(self) -> tuple[int, int]:
        return self._screen_w, self._screen_h

    def teardown(self) -> None:
        if self.udid:
            try:
                self.plane.run_sync(f"xcrun simctl shutdown {self.udid}", timeout=15)
            except Exception:
                pass
        self.plane.stop()

    # --- helpers ---

    def _idb(self, cmd: str) -> None:
        self.plane.run_sync(f"idb {cmd}", timeout=15)

    def _boot_simulator(self) -> str:
        """Find an available iOS simulator and boot it. Returns the UDID."""
        # List available simulators
        res = self.plane.run_sync(
            "xcrun simctl list devices available --json", timeout=30,
        )
        devices = json.loads(res.stdout)
        # Find an iPhone simulator (prefer iPhone 15/16)
        udid = None
        for runtime, devs in devices.get("devices", {}).items():
            if "iOS" not in runtime:
                continue
            for dev in devs:
                if "iPhone" in dev.get("name", ""):
                    udid = dev["udid"]
                    if "15" in dev["name"] or "16" in dev["name"]:
                        break  # prefer newer models
            if udid:
                break

        if not udid:
            # Create one
            res = self.plane.run_sync(
                "xcrun simctl create 'Inspector iPhone' "
                "'com.apple.CoreSimulator.SimDeviceType.iPhone-15'",
                timeout=30,
            )
            udid = res.stdout.strip()

        # Boot it
        self.plane.run_sync(f"xcrun simctl boot {udid} 2>/dev/null || true", timeout=60)
        # Wait for boot
        self.plane.run_sync(f"xcrun simctl bootstatus {udid} -b", timeout=120)

        # Get screen size from simctl
        self._detect_screen_size(udid)

        return udid

    def _detect_screen_size(self, udid: str) -> None:
        """Try to get the simulator's screen dimensions."""
        res = self.plane.run_sync(
            f"xcrun simctl io {udid} enumerate 2>/dev/null | head -5 || true",
            timeout=10,
        )
        # Fallback: take a test screenshot and check dimensions
        try:
            png = self.plane.screenshot()
            if len(png) > 100:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(png))
                self._screen_w, self._screen_h = img.size
        except Exception:
            pass  # keep defaults

    def _build_app(self, dev_command: str | None = None) -> None:
        """Build the iOS app for the simulator."""
        if dev_command:
            self.plane.run_sync(f"cd {APP_DIR} && {dev_command}", timeout=600)
            return

        # Check if it's an Expo/RN project
        res = self.plane.run_sync(f"test -f {APP_DIR}/package.json && echo yes", timeout=5)
        if res.stdout.strip() == "yes":
            # Check for expo
            res = self.plane.run_sync(
                f"cd {APP_DIR} && cat package.json", timeout=5,
            )
            pkg = json.loads(res.stdout) if res.stdout.strip() else {}
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            if "expo" in deps:
                self.plane.run_sync(
                    f"cd {APP_DIR} && npm install && npx expo run:ios --no-bundler -d {self.udid}",
                    timeout=600,
                )
                return

            if "react-native" in deps:
                self.plane.run_sync(
                    f"cd {APP_DIR} && npm install && npx react-native run-ios --simulator {self.udid}",
                    timeout=600,
                )
                return

        # Check for xcodegen project.yml
        res = self.plane.run_sync(f"test -f {APP_DIR}/project.yml && echo yes", timeout=5)
        if res.stdout.strip() == "yes":
            self.plane.run_sync(
                f"cd {APP_DIR} && xcodegen generate 2>/dev/null || true",
                timeout=60,
            )

        # Native Xcode project — find .xcodeproj or .xcworkspace
        res = self.plane.run_sync(
            f"ls -d {APP_DIR}/*.xcworkspace 2>/dev/null || ls -d {APP_DIR}/*.xcodeproj 2>/dev/null || true",
            timeout=10,
        )
        project_path = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""

        if project_path.endswith(".xcworkspace"):
            build_flag = f"-workspace {project_path}"
        elif project_path.endswith(".xcodeproj"):
            build_flag = f"-project {project_path}"
        else:
            raise RuntimeError(f"No .xcodeproj or .xcworkspace found in {APP_DIR}")

        # Get the scheme name
        scheme = self._detect_scheme(project_path)

        self.plane.run_sync(
            f"xcodebuild {build_flag} -scheme {scheme} "
            f"-sdk iphonesimulator -destination 'id={self.udid}' "
            f"CODE_SIGNING_ALLOWED=NO "
            f"-derivedDataPath {APP_DIR}/build "
            f"build 2>&1 | tail -20",
            timeout=600,
        )

    def _detect_scheme(self, project_path: str) -> str:
        res = self.plane.run_sync(
            f"xcodebuild -list -json "
            f"{'-workspace' if project_path.endswith('.xcworkspace') else '-project'} "
            f"{project_path} 2>/dev/null || true",
            timeout=30,
        )
        try:
            info = json.loads(res.stdout)
            key = "workspace" if "workspace" in info else "project"
            schemes = info[key].get("schemes", [])
            if schemes:
                return schemes[0]
        except (json.JSONDecodeError, KeyError):
            pass
        # Fallback: use the directory name
        return os.path.basename(project_path).rsplit(".", 1)[0]

    def _find_app_bundle(self) -> str:
        """Find the .app bundle in the build output."""
        res = self.plane.run_sync(
            f"find {APP_DIR}/build -name '*.app' -type d | head -1",
            timeout=15,
        )
        path = res.stdout.strip()
        if path:
            return path

        # Expo/RN may put it elsewhere
        res = self.plane.run_sync(
            f"find ~/Library/Developer/Xcode/DerivedData -name '*.app' -path '*Debug*' "
            f"-newer {APP_DIR} -type d 2>/dev/null | head -1",
            timeout=15,
        )
        path = res.stdout.strip()
        if path:
            return path

        raise RuntimeError("Could not find .app bundle after build")

    def _detect_bundle_id(self) -> str | None:
        """Try to read the bundle ID from the built app's Info.plist."""
        app_path = None
        try:
            res = self.plane.run_sync(
                f"find {APP_DIR}/build -name 'Info.plist' -path '*.app/*' | head -1",
                timeout=10,
            )
            plist = res.stdout.strip()
            if plist:
                res = self.plane.run_sync(
                    f"/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' {plist}",
                    timeout=10,
                )
                bid = res.stdout.strip()
                if bid and res.returncode == 0:
                    return bid
        except Exception:
            pass
        return None

    def _check_crash_reports(self) -> list[str]:
        """Check for new crash reports from the simulator."""
        res = self.plane.run_sync(
            "ls -t ~/Library/Logs/DiagnosticReports/*.crash 2>/dev/null | head -1",
            timeout=10,
        )
        path = res.stdout.strip()
        if not path:
            return []
        res = self.plane.run_sync(f"head -30 {path}", timeout=10)
        if res.stdout.strip():
            return [f"[crash-report] {line}" for line in res.stdout.splitlines()[:15]]
        return []


def _shell_quote(s: str) -> str:
    """Quote a string for shell, with idb-friendly escaping."""
    return "'" + s.replace("'", "'\\''") + "'"


def _idb_key(key: str) -> str:
    """Map common key names to idb key event codes."""
    mapping = {
        "Return": "13", "Enter": "13",
        "Tab": "9",
        "Escape": "27",
        "Backspace": "8", "Delete": "8",
        "Space": "32",
    }
    return mapping.get(key, key)
