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


def test_local_web_captures_network_traffic():
    """Web is where the backend bugs are: the local Chrome adapter must inherit the CDP
    Network capture rather than the base class's empty list, which reads as no traffic."""
    assert LocalWebAdapter.network is LocalElectronAdapter.network
    assert LocalWebAdapter.network is not SurfaceAdapter.network

    a = LocalWebAdapter(Config())
    assert a.network() == []                        # no CDP session yet → neutral no-op
    a.cdp = _NetworkingCDP([{"url": "http://localhost:3000/api/todos", "status": 500,
                             "failed": False, "error": ""}])
    assert a.network()[0]["status"] == 500
    assert a.logs() == []                           # console stays a separate channel


def test_local_web_can_route_and_resize():
    """Routes and responsive layouts are where web bugs live: the local Chrome adapter
    must inherit the CDP navigation/viewport primitives, not the base class's honest
    'this surface cannot' False."""
    for name in ("navigate", "go_back", "go_forward", "reload", "set_viewport"):
        assert getattr(LocalWebAdapter, name) is getattr(LocalElectronAdapter, name)
        assert getattr(LocalWebAdapter, name) is not getattr(SurfaceAdapter, name)

    a = LocalWebAdapter(Config())
    assert a.navigate("/does-not-exist") is False   # no CDP session yet → can't, and says so
    a.cdp = _NavigatingCDP("http://localhost:3000/items")
    # the file:// app-shell guard is Electron's problem; a served web app just routes
    assert a.navigate("/does-not-exist") is True
    assert a.cdp.navigated == ["http://localhost:3000/does-not-exist"]
    assert a.set_viewport(375, 667, mobile=True) is True
    assert a.screen_size() == (375, 667)            # clicks follow the resize


def test_local_web_can_seed_and_capture_a_session():
    """Web is where auth lives: without seeding, every run of a real app starts on the
    login screen and spends its iteration budget getting past it. The local Chrome
    adapter must inherit the CDP session hooks, not the base class's honest 'cannot'."""
    for name in ("seed_state", "capture_state"):
        assert getattr(LocalWebAdapter, name) is getattr(LocalElectronAdapter, name)
        assert getattr(LocalWebAdapter, name) is not getattr(SurfaceAdapter, name)

    a = LocalWebAdapter(Config())
    assert a.capture_state() == {}                  # no CDP session yet → nothing to say
    assert a.seed_state(_STATE) is False            # ...and it says so rather than lying

    a.cdp = _SessionCDP("http://localhost:3000/login")
    assert a.seed_state(_STATE) is True
    assert a.cdp.calls == ["set_cookies", "set_storage", "reload"]   # already on the origin
    assert a.capture_state() == _STATE


_STATE = {"origin": "http://localhost:3000",
          "cookies": [{"name": "sid", "value": "abc", "domain": "localhost"}],
          "local_storage": {"token": "ey.J"}, "session_storage": {}}


class _SessionCDP:
    def __init__(self, url):
        self.url = url
        self.jar: list[dict] = []
        self.local: dict = {}
        self.session: dict = {}
        self.calls: list[str] = []

    def current_url(self):
        return self.url

    def get_cookies(self, urls=None):
        return [dict(c) for c in self.jar]

    def get_storage(self, origin=""):
        return {"local": dict(self.local), "session": dict(self.session)}

    def set_cookies(self, cookies):
        self.calls.append("set_cookies")
        self.jar = [dict(c) for c in cookies]
        return True

    def set_storage(self, origin, local=None, session=None):
        self.calls.append("set_storage")
        self.local.update(local or {})
        self.session.update(session or {})
        return True

    def reload(self):
        self.calls.append("reload")
        return True


class _NavigatingCDP:
    def __init__(self, url):
        self.url = url
        self.navigated: list[str] = []

    def current_url(self):
        return self.url

    def navigate(self, url):
        self.navigated.append(url)
        return True

    def set_viewport(self, width, height, mobile=False):
        return True


class _AuditingCDP:
    def __init__(self, result):
        self._result = result

    def audit_dom(self):
        return self._result


class _NetworkingCDP:
    def __init__(self, records):
        self._records = records

    def drain_network(self):
        return self._records

    def drain_console(self):
        return []


# The old `test_falls_back_to_e2b_without_config` lived here and asserted that local
# execution WITHOUT the two env vars dropped through to the billed E2B adapter. That
# was the bug, not the contract: local now means local unconditionally. Its replacement
# is tests/test_adapter_selection.py::test_local_web_without_any_env_uses_local_adapter.
