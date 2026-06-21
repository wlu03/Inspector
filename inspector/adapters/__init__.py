from __future__ import annotations

from ..config import Config
from ..models import Surface
from .android import AndroidAdapter
from .base import InputAction, SurfaceAdapter
from .electron import ElectronAdapter
from .ios import IOSAdapter
from .web import WebAdapter

REGISTRY: dict[Surface, type[SurfaceAdapter]] = {
    Surface.WEB: WebAdapter,
    Surface.ELECTRON: ElectronAdapter,
    Surface.ANDROID: AndroidAdapter,
    Surface.IOS: IOSAdapter,
}


def get_adapter(surface: Surface, config: Config, repo_path: str | None = None) -> SurfaceAdapter:
    # Framework override: Expo/RN can't boot natively in the Linux plane, so run it
    # as a web preview (ExpoWebAdapter) — same workflow, real running app.
    # Expo/RN picks its plane by the REQUESTED surface: WEB → fast web preview
    # (ExpoWebAdapter); ANDROID/IOS → the native device path (Android emulator / iOS
    # simulator) via the normal registry. So `surface="android"` reaches AndroidAdapter.
    if repo_path and surface == Surface.WEB:
        try:
            from ..launch.detect import detect_project
            if detect_project(repo_path).framework == "expo":
                from .expo import ExpoWebAdapter
                return ExpoWebAdapter(config)
        except Exception:
            pass
    # Local execution: drive Electron on the host via CDP (no VM, no xdotool).
    if config.execution == "local" and surface == Surface.ELECTRON:
        from .local_electron import LocalElectronAdapter
        return LocalElectronAdapter(config)
    return REGISTRY[surface](config)


__all__ = ["SurfaceAdapter", "InputAction", "get_adapter", "REGISTRY"]
