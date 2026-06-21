"""The localhost dashboard server + the test-finish link it hands back."""
from __future__ import annotations

import json
import os
import urllib.request

from inspector.dashboard.build import build_dashboard
from inspector.dashboard.serve import ensure_server, publish


def _mini(root: str, sid: str = "ses_z") -> None:
    sdir = os.path.join(root, sid)
    os.makedirs(os.path.join(sdir, "findings"), exist_ok=True)
    with open(os.path.join(sdir, "session.json"), "w") as f:
        json.dump({"id": sid, "surface": "web", "goal": "g", "state": "torn_down",
                   "repo_path": "/r", "created_at": "2026-06-01T00:00:00"}, f)


def test_ensure_server_serves_the_dashboard(tmp_path):
    root = str(tmp_path)
    _mini(root)
    build_dashboard(root)
    url = ensure_server(root, port=0)            # ephemeral port (no clash with a live 7321)
    assert ensure_server(root, port=0) == url     # singleton: reused, not restarted
    assert url.startswith("http://127.0.0.1:")
    body = urllib.request.urlopen(url + "/dashboard.html", timeout=5).read().decode()
    assert "ses_z" in body                        # the run shows up over HTTP


def test_publish_returns_deeplink_and_replay_url(tmp_path):
    root = str(tmp_path)
    _mini(root)
    links = publish(root, "ses_z", port=0)
    assert links["dashboard_url"].endswith("/dashboard.html#ses_z")  # highlights the run
    assert links["replay_url"].endswith("/ses_z/index.html")
    assert os.path.exists(os.path.join(root, "dashboard.html"))      # built as a side effect


def test_publish_without_session_is_plain_dashboard(tmp_path):
    root = str(tmp_path)
    _mini(root)
    links = publish(root, port=0)
    assert links["dashboard_url"].endswith("/dashboard.html")
    assert "replay_url" not in links


def test_live_endpoint_serves_provider_data(tmp_path):
    from inspector.dashboard import serve

    root = str(tmp_path)
    _mini(root)
    serve.set_live_provider(lambda: {"sessions": [{"id": "ses_live", "goal": "running"}]})
    try:
        url = ensure_server(root, port=0)
        body = urllib.request.urlopen(url + "/live.json", timeout=5).read().decode()
        assert json.loads(body)["sessions"][0]["id"] == "ses_live"
    finally:
        serve.set_live_provider(None)


def test_live_endpoint_empty_without_provider(tmp_path):
    from inspector.dashboard import serve

    root = str(tmp_path)
    _mini(root)
    serve.set_live_provider(None)
    url = ensure_server(root, port=0)
    body = urllib.request.urlopen(url + "/live.json", timeout=5).read().decode()
    assert json.loads(body) == {"sessions": []}
