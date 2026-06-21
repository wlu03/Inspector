from __future__ import annotations

import os
import time

from ..config import Config
from ..models import ActionType, Surface
from ..planes.android import RedroidRuntime
from ..planes.linux import LinuxPlane
from .base import InputAction, SurfaceAdapter

APK_DIR = "/home/user/app"
BUILD_DIR = "/home/user/app/android"


class AndroidAdapter(SurfaceAdapter):
    """Android via Redroid + adb inside an E2B Linux sandbox. See docs/11 Part J.

    The adapter:
      1. Boots the LinuxPlane (E2B sandbox)
      2. Starts a Redroid container inside it
      3. Builds the APK (Expo/RN/native Gradle)
      4. Installs + launches the app via adb
      5. Interacts via adb input, captures via adb screencap, detects crashes via logcat
    """

    surface = Surface.ANDROID

    def __init__(self, config: Config):
        self.config = config
        self.plane = LinuxPlane(config)
        self.redroid: RedroidRuntime | None = None
        self.package: str | None = None
        self._screen_w = 1080
        self._screen_h = 1920
        self._log_offset = 0
        self._node_path = "export PATH=/home/user/node/bin:$PATH"
        self._android_env = ""
        self._sdk_root = "/home/user/android-sdk"

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        # Boot the E2B sandbox
        self.plane.start()

        # Upload the app source
        self.plane.upload(repo_path, APK_DIR)

        # Install adb + docker prerequisites
        self._install_prereqs()

        # Start Redroid
        self.redroid = RedroidRuntime(
            self.plane,
            width=self._screen_w,
            height=self._screen_h,
        )
        self.redroid.start()

        # Build the APK
        apk_path = self._build_apk(dev_command)

        # Install the APK
        self.redroid.install(apk_path)

        # Detect the package name
        self.package = self._detect_package(apk_path)

        # Clear logcat before launch
        self.redroid.logcat_clear()

        # Launch the app
        self.redroid.launch(self.package)

    def is_ready(self, timeout_s: float = 30.0) -> bool:
        """Wait until the app's main activity is in the foreground."""
        if not self.redroid or not self.package:
            return False
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            pid = self.redroid.pid_of(self.package)
            if pid:
                time.sleep(2)  # settle time
                return True
            time.sleep(1)
        return False

    def screenshot(self) -> bytes:
        if not self.redroid:
            raise RuntimeError("Redroid not started")
        return self.redroid.screenshot()

    def input(self, action: InputAction) -> None:
        if not self.redroid:
            raise RuntimeError("Redroid not started")

        t = action.type
        if t == ActionType.CLICK:
            self.redroid.tap(action.x, action.y)
        elif t == ActionType.DOUBLE_CLICK:
            self.redroid.tap(action.x, action.y)
            time.sleep(0.05)
            self.redroid.tap(action.x, action.y)
        elif t == ActionType.TYPE:
            self.redroid.text(action.text or "")
        elif t == ActionType.KEY:
            code = _android_keycode(action.key or "")
            self.redroid.keyevent(code)
        elif t == ActionType.SCROLL:
            cx, cy = self._screen_w // 2, self._screen_h // 2
            dist = 400 * action.amount
            if action.direction == "down":
                self.redroid.swipe(cx, cy, cx, cy - dist)
            elif action.direction == "up":
                self.redroid.swipe(cx, cy, cx, cy + dist)
            elif action.direction == "left":
                self.redroid.swipe(cx, cy, cx + dist, cy)
            elif action.direction == "right":
                self.redroid.swipe(cx, cy, cx - dist, cy)
        elif t == ActionType.WAIT:
            time.sleep(1)

    def logs(self) -> list[str]:
        if not self.redroid or not self.package:
            return []

        lines: list[str] = []

        # Check crash buffer
        crash_log = self.redroid.logcat_crash()
        crash_lines = crash_log.splitlines()
        new_crash = crash_lines[self._log_offset:]
        self._log_offset = len(crash_lines)
        lines.extend(new_crash)

        # Check if the process is still alive
        pid = self.redroid.pid_of(self.package)
        if not pid:
            lines.append(f"[inspector] process {self.package} is not running (crashed?)")

        return lines

    def rendered_elements(self) -> list[str]:
        # Same oracle contract as web/iOS — only the source differs: the native view
        # hierarchy. `adb exec-out uiautomator dump /dev/tty` → parse the XML for
        # clickable nodes' text/content-desc. Wired with the rest of M2.
        raise NotImplementedError(
            "AndroidAdapter.rendered_elements — uiautomator hierarchy (docs/11 Part J)"
        )

    def screen_size(self) -> tuple[int, int]:
        return self._screen_w, self._screen_h

    def teardown(self) -> None:
        if self.redroid:
            if self.package:
                try:
                    self.redroid.force_stop(self.package)
                except Exception:
                    pass
            try:
                self.redroid.stop()
            except Exception:
                pass
        try:
            self.plane.stop()
        except Exception:
            pass

    # --- helpers ---

    def _install_prereqs(self) -> None:
        """Install adb, Docker, JDK, and Node in the E2B sandbox."""
        # Node.js (same method as WebAdapter)
        node_version = "v22.11.0"
        node_dir = "/home/user/node"
        self.plane.run_sync(
            f"test -x {node_dir}/bin/node || "
            f"(cd /home/user && curl -fsSL https://nodejs.org/dist/{node_version}/"
            f"node-{node_version}-linux-x64.tar.xz -o node.tar.xz && "
            f"tar -xJf node.tar.xz && mv node-{node_version}-linux-x64 {node_dir})",
            timeout=300,
        )
        self._node_path = f"export PATH={node_dir}/bin:$PATH"

        # adb
        self.plane.run_sync(
            "which adb || (sudo apt-get update -qq && sudo apt-get install -y -qq android-tools-adb) "
            "2>/dev/null || true",
            timeout=120,
        )
        # Docker
        self.plane.run_sync(
            "which docker || (curl -fsSL https://get.docker.com | sudo sh) 2>/dev/null || true",
            timeout=180,
        )
        # JDK 17
        self.plane.run_sync(
            "which javac || (sudo apt-get update -qq && sudo apt-get install -y -qq openjdk-17-jdk-headless) "
            "2>/dev/null || true",
            timeout=180,
        )
        # Android SDK — minimal setup: just create the directory and accept licenses.
        # Gradle downloads the actual SDK components it needs automatically.
        sdk_root = "/home/user/android-sdk"
        self.plane.run_sync(f"mkdir -p {sdk_root}/licenses", timeout=5)
        # Pre-accept all SDK licenses by writing the hash files Gradle checks
        self.plane.run_sync(
            f"echo -e '\\n24333f8a63b6825ea9c5514f83c2829b004d1fee' > {sdk_root}/licenses/android-sdk-license && "
            f"echo -e '\\n84831b9409646a918e30573bab4c9c91346d8abd' > {sdk_root}/licenses/android-sdk-preview-license && "
            f"echo -e '\\nd56f5187479451eabf01fb78af6dfcb131a6481e\\n24333f8a63b6825ea9c5514f83c2829b004d1fee' >> {sdk_root}/licenses/android-sdk-license && "
            f"echo -e '\\ne9acab5b5fbb560a72797e95dcdf135e1b3bf903' > {sdk_root}/licenses/android-sdk-arm-dbt-license && "
            f"echo -e '\\n859f317696f67ef3d7f30a50a5560e7834b43903' > {sdk_root}/licenses/android-googletv-license && "
            f"echo -e '\\n33b6a2b64607f11b759f320ef9dff4ae5c47d97a' > {sdk_root}/licenses/google-gdk-license && "
            f"echo -e '\\nd975f751698a77e662f1cd747666ef6b2c0c862f' > {sdk_root}/licenses/intel-android-extra-license && "
            f"echo -e '\\n33b6a2b64607f11b759f320ef9dff4ae5c47d97a' > {sdk_root}/licenses/mips-android-sysimage-license",
            timeout=10,
        )
        self._android_env = (
            f"export ANDROID_HOME={sdk_root} && "
            f"export ANDROID_SDK_ROOT={sdk_root} && "
            f"export PATH={sdk_root}/platform-tools:$PATH"
        )
        self._sdk_root = sdk_root

    def _build_apk(self, dev_command: str | None = None) -> str:
        """Build the APK and return its path inside the sandbox."""
        if dev_command:
            self.plane.run_sync(f"cd {APK_DIR} && {dev_command}", timeout=600)
            return self._find_apk()

        # Check for package.json (Expo/RN)
        res = self.plane.run_sync(f"test -f {APK_DIR}/package.json && echo yes", timeout=5)
        stdout = res.stdout.strip() if res and getattr(res, "stdout", "") else ""

        if stdout == "yes":
            # npm install
            self.plane.run_sync(
                f"{self._node_path} && cd {APK_DIR} && npm install",
                timeout=300,
            )

            # Check if Expo
            res = self.plane.run_sync(
                f"{self._node_path} && cd {APK_DIR} && node -e \"const p=require('./package.json'); "
                f"console.log(p.dependencies && p.dependencies.expo ? 'expo' : 'rn')\"",
                timeout=10,
            )
            framework = res.stdout.strip() if res and getattr(res, "stdout", "") else ""

            if framework == "expo":
                # Expo: prebuild then gradle
                self.plane.run_sync(
                    f"{self._node_path} && cd {APK_DIR} && npx expo prebuild -p android --no-install",
                    timeout=300,
                )
                self._write_local_properties()
                # expo-modules-core needs cmake; also set ANDROID_NDK_HOME
                ndk_home = f"{self._sdk_root}/ndk/26.1.10909125"
                self.plane.run_sync(
                    f"{self._node_path} && {self._android_env} && "
                    f"export ANDROID_NDK_HOME={ndk_home} && "
                    f"cd {APK_DIR}/android && chmod +x gradlew && "
                    f"./gradlew assembleDebug -x lint",
                    timeout=600,
                )
            else:
                # Plain React Native
                self._write_local_properties()
                self.plane.run_sync(
                    f"{self._node_path} && {self._android_env} && "
                    f"cd {APK_DIR}/android && chmod +x gradlew && ./gradlew assembleDebug",
                    timeout=600,
                )
        else:
            # Native Android (Gradle project)
            self._write_local_properties()
            self.plane.run_sync(
                f"{self._node_path} && {self._android_env} && "
                f"cd {APK_DIR} && chmod +x gradlew && ./gradlew assembleDebug",
                timeout=600,
            )

        return self._find_apk()

    def _write_local_properties(self) -> None:
        """Write local.properties so Gradle finds the Android SDK."""
        self.plane.run_sync(
            f"echo 'sdk.dir={self._sdk_root}' > {APK_DIR}/android/local.properties 2>/dev/null || true",
            timeout=5,
        )

    def _find_apk(self) -> str:
        """Find the built APK."""
        res = self.plane.run_sync(
            f"find {APK_DIR} -name '*.apk' -path '*debug*' -o -name '*.apk' | head -1",
            timeout=15,
        )
        path = res.stdout.strip() if res and getattr(res, "stdout", "") else ""
        if path:
            return path
        raise RuntimeError(f"No APK found after build in {APK_DIR}")

    def _detect_package(self, apk_path: str) -> str:
        """Extract the package name from the APK."""
        res = self.redroid.adb(
            f"shell pm list packages -f 2>/dev/null | tail -5", timeout=10,
        )
        # Try aapt if available
        res2 = self.plane.run_sync(
            f"aapt dump badging {apk_path} 2>/dev/null | head -1 || true",
            timeout=10,
        )
        stdout = res2.stdout if res2 and getattr(res2, "stdout", "") else ""
        if "package: name=" in stdout:
            # parse: package: name='com.example.app' ...
            start = stdout.index("name='") + 6
            end = stdout.index("'", start)
            return stdout[start:end]

        # Fallback: read from package.json
        res3 = self.plane.run_sync(
            f"{self._node_path} && cd {APK_DIR} && node -e \"const p=require('./package.json'); "
            f"console.log(p.name || 'com.inspector.sample')\" 2>/dev/null || echo com.inspector.sample",
            timeout=10,
        )
        name = res3.stdout.strip() if res3 and getattr(res3, "stdout", "") else "com.inspector.sample"
        # Expo convention: host.exp.exponent or com.<name>
        return f"com.{name.replace('-', '')}" if "." not in name else name


def _android_keycode(key: str) -> str:
    """Map common key names to Android keycodes."""
    mapping = {
        "Return": "66", "Enter": "66",
        "Tab": "61",
        "Escape": "111",
        "Backspace": "67", "Delete": "67",
        "Space": "62",
        "Home": "3",
        "Back": "4",
        "Up": "19", "Down": "20", "Left": "21", "Right": "22",
    }
    return mapping.get(key, key)
