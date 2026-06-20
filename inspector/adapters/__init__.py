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


def get_adapter(surface: Surface, config: Config) -> SurfaceAdapter:
    return REGISTRY[surface](config)


__all__ = ["SurfaceAdapter", "InputAction", "get_adapter", "REGISTRY"]
