from __future__ import annotations

from ..launch.detect import detect_project
from ..models import Surface
from .web import APP_DIR, NODE_DIR, WebAdapter

# Expo's web target needs these; the stock RN template ships without them. `expo
# install` resolves SDK-compatible versions (don't pin — they track the Expo SDK).
# expo-asset/expo-constants are core packages Metro's config loads at startup — a
# minimal/hand-written app may omit them, so install them too.
_EXPO_WEB_DEPS = "react-native-web react-dom @expo/metro-runtime expo-asset expo-constants"

# Expo (Metro) web dev server port.
_EXPO_WEB_PORT = 8081


class ExpoWebAdapter(WebAdapter):
    """Boot an Expo / React Native app as a WEB PREVIEW on the Linux plane.

    Native RN needs an emulator (the Android/iOS planes); Expo's web target lets the
    *same* app actually run and be driven here today — not just statically scanned.
    It reuses the entire web workflow unchanged: Chrome + CDP console tap, screenshot
    cropping, `rendered_elements`, and the missing-element oracle. Only the boot
    command differs (`expo start --web` instead of a vite/next dev server).
    """

    surface = Surface.WEB

    def launch(self, repo_path: str, dev_command: str | None = None) -> None:
        # It's an Expo/RN project; record the real framework, run it on the web target.
        self.project = detect_project(repo_path, Surface.ANDROID)
        self._port = _EXPO_WEB_PORT
        self.sandbox.start()
        self.sandbox.upload_dir(repo_path)
        self._ensure_node()
        node = f"export PATH={NODE_DIR}/bin:$PATH && cd {APP_DIR}"
        self.sandbox.run_sync(f"{node} && npm install", timeout=600)
        # add the web-target deps (idempotent; expo picks SDK-compatible versions)
        self.sandbox.run_sync(f"{node} && CI=1 npx expo install {_EXPO_WEB_DEPS}", timeout=420)
        cmd = dev_command or f"npx expo start --web --port {_EXPO_WEB_PORT}"
        self.sandbox.run_dev(
            f"{node} && {cmd}",
            envs={"CI": "1", "BROWSER": "none", "EXPO_NO_TELEMETRY": "1"},
        )

    def is_ready(self, timeout_s: float = 240.0) -> bool:
        # Metro's first web bundle is much slower than a vite cold start — wait longer.
        return super().is_ready(timeout_s=timeout_s)
