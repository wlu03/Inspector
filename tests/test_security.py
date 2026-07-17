"""Security-hardening tests (Phase 2B): path traversal, host-exec gating, dashboard CSRF."""

from __future__ import annotations

import os

import pytest

from inspector.config import Config, _split_paths
from inspector.models import Surface
from inspector.paths import safe_repo_path, valid_id


def test_valid_id_accepts_real_ids():
    assert valid_id("ses_0a1b2c")
    assert valid_id("trc_9f")
    assert valid_id("finding-123")


@pytest.mark.parametrize(
    "bad", ["", "..", "../etc", "a/b", "a\\b", "/abs", ".", "with space", "x" * 200]
)
def test_valid_id_rejects_traversal(bad):
    assert not valid_id(bad)


def test_safe_repo_path_canonicalizes(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    assert safe_repo_path(str(d / ".." / "app")) == os.path.realpath(str(d))


def test_safe_repo_path_enforces_workspace_roots(tmp_path):
    root = tmp_path / "ws"
    (root / "app").mkdir(parents=True)
    assert safe_repo_path(str(root / "app"), [str(root)]) == os.path.realpath(str(root / "app"))
    with pytest.raises(PermissionError):
        safe_repo_path(str(tmp_path / "elsewhere"), [str(root)])


def test_aggregate_rejects_traversal_ids(tmp_path):
    from inspector.dashboard.aggregate import (
        load_session_detail,
        signature_for_finding,
        update_finding_status,
    )

    tr = str(tmp_path)
    assert load_session_detail(tr, "../../etc")["session"] is None
    assert "invalid" in update_finding_status(tr, "../x", "fid", "fixed")["error"]
    assert signature_for_finding(tr, "../x", "fid") is None


def test_local_exec_refused_over_http():
    from inspector.adapters import get_adapter

    with pytest.raises(PermissionError):
        get_adapter(Surface.ELECTRON, Config(execution="local", transport="http"))


def test_local_exec_allowed_for_stdio_and_optin():
    from inspector.adapters import get_adapter

    assert get_adapter(Surface.ELECTRON, Config(execution="local", transport="stdio"))
    assert get_adapter(
        Surface.ELECTRON, Config(execution="local", transport="http", allow_unsafe_local=True)
    )


def test_dashboard_local_only_guard():
    from inspector.dashboard.serve import _QuietHandler

    class _Fake:
        def __init__(self, headers):
            self.headers = headers

    assert _QuietHandler._local_only(_Fake({"Host": "127.0.0.1:7321"}))
    assert not _QuietHandler._local_only(
        _Fake({"Host": "127.0.0.1:7321", "Origin": "http://evil.example"})
    )
    assert not _QuietHandler._local_only(_Fake({"Host": "evil.example"}))


def test_http_non_loopback_bind_refused():
    from inspector.server import main

    with pytest.raises(SystemExit):
        main(["--http", "--host", "0.0.0.0"])


def test_config_env_parsing(monkeypatch):
    monkeypatch.setenv("INSPECTOR_ALLOW_UNSAFE_LOCAL", "1")
    monkeypatch.setenv("INSPECTOR_WORKSPACE_ROOTS", f"/a{os.pathsep}/b,/c")
    cfg = Config.from_env()
    assert cfg.allow_unsafe_local is True
    assert cfg.workspace_roots == ["/a", "/b", "/c"]


def test_split_paths():
    assert _split_paths(None) == []
    assert _split_paths(f" /a {os.pathsep} /b , /c ") == ["/a", "/b", "/c"]
