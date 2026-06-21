"""Expo routing: an Expo/RN project boots via the web-preview adapter, not native."""
from __future__ import annotations

import json

from inspector.adapters import get_adapter
from inspector.adapters.expo import ExpoWebAdapter
from inspector.adapters.web import WebAdapter
from inspector.config import Config
from inspector.models import Surface


def _expo_repo(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"expo": "~52.0.0", "react-native": "0.76.0"},
        "scripts": {"start": "expo start"},
    }))
    return str(tmp_path)


def test_expo_web_surface_routes_to_web_preview(tmp_path):
    # surface="web" → fast web preview
    adapter = get_adapter(Surface.WEB, Config(), repo_path=_expo_repo(tmp_path))
    assert isinstance(adapter, ExpoWebAdapter)
    assert adapter.surface == Surface.WEB


def test_expo_android_surface_routes_to_native_android(tmp_path):
    # surface="android" → native device path (local emulator), NOT web preview
    from inspector.adapters.android import AndroidAdapter
    adapter = get_adapter(Surface.ANDROID, Config(), repo_path=_expo_repo(tmp_path))
    assert isinstance(adapter, AndroidAdapter)
    assert not isinstance(adapter, ExpoWebAdapter)


def test_expo_adapter_inherits_web_workflow():
    # rendered_elements / CDP / oracle all come from WebAdapter unchanged
    assert issubclass(ExpoWebAdapter, WebAdapter)


def test_plain_web_project_unaffected(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps(
        {"devDependencies": {"vite": "^5"}, "scripts": {"dev": "vite"}}))
    adapter = get_adapter(Surface.WEB, Config(), repo_path=str(tmp_path))
    assert isinstance(adapter, WebAdapter) and not isinstance(adapter, ExpoWebAdapter)
