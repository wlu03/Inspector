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


def _guard_local_exec(config: Config) -> None:
    """Host (non-sandboxed) execution runs the app + dev_command on this machine. Fine
    for the local stdio client, but over the HTTP transport it is arbitrary code
    execution for a networked caller — refuse unless explicitly opted in."""
    if config.transport != "stdio" and not config.allow_unsafe_local:
        raise PermissionError(
            "host/local execution is disabled over the HTTP transport; set "
            "INSPECTOR_ALLOW_UNSAFE_LOCAL=1 to allow running the app on the host, "
            "or use the sandboxed plane."
        )


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
        _guard_local_exec(config)
        from .local_electron import LocalElectronAdapter
        return LocalElectronAdapter(config)
    # Local web via headless Chrome — opt-in when a URL or prebuilt dist is configured
    # (for real apps like Angular/Capacitor that don't fit the E2B build-and-serve path).
    import os as _os
    if (config.execution == "local" and surface == Surface.WEB
            and (_os.environ.get("INSPECTOR_WEB_URL") or _os.environ.get("INSPECTOR_WEB_DIST"))):
        _guard_local_exec(config)
        from .local_web import LocalWebAdapter
        return LocalWebAdapter(config)
    # Native macOS apps are local-only (AX tree + CGEvent on the host).
    if surface == Surface.MACOS:
        _guard_local_exec(config)
        from .macos_native import MacNativeAdapter
        return MacNativeAdapter(config)
    return REGISTRY[surface](config)


__all__ = ["SurfaceAdapter", "InputAction", "get_adapter", "REGISTRY"]
