"""Tests for the local headless-Chrome web adapter + its routing."""
from __future__ import annotations

import json

from inspector.adapters import get_adapter
from inspector.adapters.local_web import LocalWebAdapter, chrome_bin
from inspector.config import Config
from inspector.models import Surface


def test_chrome_bin_returns_something():
    b = chrome_bin()
    assert "Chrome" in b or "hromium" in b or b == "google-chrome"


def test_routes_to_local_web_when_dist_configured(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vite": "^5"}}))
    monkeypatch.setenv("INSPECTOR_WEB_DIST", str(tmp_path))
    a = get_adapter(Surface.WEB, Config(execution="local"), repo_path=str(tmp_path))
    assert isinstance(a, LocalWebAdapter)
    assert a.surface == Surface.WEB


def test_routes_to_local_web_when_url_configured(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vite": "^5"}}))
    monkeypatch.delenv("INSPECTOR_WEB_DIST", raising=False)
    monkeypatch.setenv("INSPECTOR_WEB_URL", "http://localhost:4200")
    a = get_adapter(Surface.WEB, Config(execution="local"), repo_path=str(tmp_path))
    assert isinstance(a, LocalWebAdapter)


def test_falls_back_to_e2b_without_config(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vite": "^5"}}))
    monkeypatch.delenv("INSPECTOR_WEB_DIST", raising=False)
    monkeypatch.delenv("INSPECTOR_WEB_URL", raising=False)
    a = get_adapter(Surface.WEB, Config(execution="local"), repo_path=str(tmp_path))
    assert not isinstance(a, LocalWebAdapter)   # the E2B WebAdapter, unchanged
