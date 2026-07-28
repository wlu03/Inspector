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
    # Local web via headless Chrome. Unconditional: LocalWebAdapter resolves its URL
    # from INSPECTOR_WEB_URL, then INSPECTOR_WEB_DIST, then the project's own dev
    # command — so it works with no env vars set. Gating it on those two used to drop
    # a "local" caller through to the E2B WebAdapter, which then billed a sandbox and
    # died on a missing key; local must mean local.
    if config.execution == "local" and surface == Surface.WEB:
        _guard_local_exec(config)
        from .local_web import LocalWebAdapter
        return LocalWebAdapter(config)
    # Native macOS apps are local-only (AX tree + CGEvent on the host).
    if surface == Surface.MACOS:
        _guard_local_exec(config)
        from .macos_native import MacNativeAdapter
        return MacNativeAdapter(config)
    # Everything left for web/Electron is the E2B Linux plane. Fail here, with the name
    # of the missing key and the local alternative, rather than several layers deeper
    # inside the e2b client where the error is an opaque auth failure. Android/iOS use
    # their own planes (emulator / tart), so they are not gated on this.
    if surface in (Surface.WEB, Surface.ELECTRON) and not config.e2b_api_key:
        raise RuntimeError(
            f"sandboxed execution of the {surface.value} surface needs E2B_API_KEY, which is "
            "not set. Set it, or run the app on this machine instead with "
            "INSPECTOR_EXECUTION=local."
        )
    return REGISTRY[surface](config)


__all__ = ["SurfaceAdapter", "InputAction", "get_adapter", "REGISTRY"]
