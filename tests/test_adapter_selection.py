"""Tests for `get_adapter` routing — which plane a (surface, config) pair lands on.

The bug these pin down: asking for local execution used to route WEB to the E2B
sandbox adapter unless INSPECTOR_WEB_URL/INSPECTOR_WEB_DIST happened to be set, so a
user who said "run this locally" silently got a billed sandbox and an opaque auth
failure. Routing is pure dispatch, so every case here asserts on the returned class
and never launches anything — no adapter constructed below spawns a process.
"""
from __future__ import annotations

import json

import pytest

from inspector.adapters import get_adapter
from inspector.adapters.expo import ExpoWebAdapter
from inspector.adapters.local_electron import LocalElectronAdapter
from inspector.adapters.local_web import LocalWebAdapter
from inspector.config import Config
from inspector.models import Surface


@pytest.fixture(autouse=True)
def _clear_web_env(monkeypatch):
    """The web-URL/dist vars leak in from a developer's real .env; routing must not
    depend on them, so every test starts from neither being set."""
    monkeypatch.delenv("INSPECTOR_WEB_URL", raising=False)
    monkeypatch.delenv("INSPECTOR_WEB_DIST", raising=False)


def _vite_repo(tmp_path) -> str:
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vite": "^5"}}))
    return str(tmp_path)


def _expo_repo(tmp_path) -> str:
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"expo": "~52.0.0", "react-native": "0.76.0"},
        "scripts": {"start": "expo start"},
    }))
    return str(tmp_path)


def test_local_web_without_any_env_uses_local_adapter(tmp_path):
    """The regression: no INSPECTOR_WEB_* set at all still stays on the host, where
    LocalWebAdapter falls back to running the project's own dev command."""
    adapter = get_adapter(Surface.WEB, Config(execution="local"), repo_path=_vite_repo(tmp_path))
    assert isinstance(adapter, LocalWebAdapter)
    assert adapter.surface == Surface.WEB


def test_local_web_without_repo_path_uses_local_adapter():
    adapter = get_adapter(Surface.WEB, Config(execution="local"))
    assert isinstance(adapter, LocalWebAdapter)


def test_local_web_with_url_configured_uses_local_adapter(monkeypatch, tmp_path):
    """Configuring a URL is still honoured — it now selects LocalWebAdapter's fastest
    path rather than being the thing that selects the adapter at all."""
    monkeypatch.setenv("INSPECTOR_WEB_URL", "http://localhost:4200")
    adapter = get_adapter(Surface.WEB, Config(execution="local"), repo_path=_vite_repo(tmp_path))
    assert isinstance(adapter, LocalWebAdapter)


def test_local_web_with_dist_configured_uses_local_adapter(monkeypatch, tmp_path):
    monkeypatch.setenv("INSPECTOR_WEB_DIST", str(tmp_path))
    adapter = get_adapter(Surface.WEB, Config(execution="local"), repo_path=_vite_repo(tmp_path))
    assert isinstance(adapter, LocalWebAdapter)


def test_local_web_over_http_transport_still_guarded():
    """Making local web unconditional must not widen the remote-caller hole: host
    execution over HTTP is still refused unless explicitly opted in."""
    config = Config(execution="local", transport="http", allow_unsafe_local=False)
    with pytest.raises(PermissionError):
        get_adapter(Surface.WEB, config)


def test_sandboxed_web_without_key_raises_actionable_error():
    with pytest.raises(RuntimeError) as excinfo:
        get_adapter(Surface.WEB, Config(execution="vm", e2b_api_key=None))
    message = str(excinfo.value)
    assert "E2B_API_KEY" in message
    assert "INSPECTOR_EXECUTION=local" in message


def test_sandboxed_electron_without_key_raises_actionable_error():
    with pytest.raises(RuntimeError) as excinfo:
        get_adapter(Surface.ELECTRON, Config(execution="vm", e2b_api_key=None))
    assert "E2B_API_KEY" in str(excinfo.value)


def test_sandboxed_web_with_key_reaches_the_e2b_adapter():
    from inspector.adapters.web import WebAdapter
    adapter = get_adapter(Surface.WEB, Config(execution="vm", e2b_api_key="e2b_test"))
    assert isinstance(adapter, WebAdapter)


def test_local_electron_still_uses_local_adapter():
    adapter = get_adapter(Surface.ELECTRON, Config(execution="local"))
    assert isinstance(adapter, LocalElectronAdapter)
    assert not isinstance(adapter, LocalWebAdapter)


def test_expo_repo_still_overrides_to_web_preview(tmp_path):
    """Expo/RN can't boot natively in the Linux plane, so a WEB request on an Expo repo
    is redirected to the Metro web preview — ahead of any execution-mode routing."""
    adapter = get_adapter(Surface.WEB, Config(execution="local"), repo_path=_expo_repo(tmp_path))
    assert isinstance(adapter, ExpoWebAdapter)


def test_expo_repo_on_android_surface_is_untouched(tmp_path):
    from inspector.adapters.android import AndroidAdapter
    adapter = get_adapter(Surface.ANDROID, Config(), repo_path=_expo_repo(tmp_path))
    assert isinstance(adapter, AndroidAdapter)
