"""Tests for the local headless-Chrome web adapter + its routing."""
from __future__ import annotations

import json

from inspector.adapters import get_adapter
from inspector.adapters.base import SurfaceAdapter
from inspector.adapters.local_electron import LocalElectronAdapter
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


def test_local_web_runs_the_deterministic_audit():
    """The default no-API-key config routes web here; it must NOT inherit the base
    class's empty audit, which returned {} and read to the caller as a clean pass."""
    assert LocalWebAdapter.audit_dom is LocalElectronAdapter.audit_dom
    assert LocalWebAdapter.audit_dom is not SurfaceAdapter.audit_dom

    a = LocalWebAdapter(Config())
    assert a.audit_dom() == {}                      # no CDP session yet → neutral no-op
    a.cdp = _AuditingCDP({"broken_images": ["hero.png"], "axe_error": "CSP blocked axe"})
    out = a.audit_dom()
    assert out["broken_images"] == ["hero.png"] and out["axe_error"]


class _AuditingCDP:
    def __init__(self, result):
        self._result = result

    def audit_dom(self):
        return self._result


# The old `test_falls_back_to_e2b_without_config` lived here and asserted that local
# execution WITHOUT the two env vars dropped through to the billed E2B adapter. That
# was the bug, not the contract: local now means local unconditionally. Its replacement
# is tests/test_adapter_selection.py::test_local_web_without_any_env_uses_local_adapter.
