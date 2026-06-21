"""Unit tests for the iOS adapter and MacOSPlane (no VM required)."""
import json

from inspector.adapters.ios import IOSAdapter, _idb_key, _shell_quote
from inspector.adapters.base import InputAction
from inspector.config import Config
from inspector.models import ActionType, Surface
from inspector.planes.macos import MacOSPlane, _CmdResult


def test_ios_adapter_surface():
    assert IOSAdapter.surface == Surface.IOS


def test_ios_adapter_init():
    config = Config()
    adapter = IOSAdapter(config)
    assert adapter.plane is not None
    assert adapter.udid is None
    assert adapter.bundle_id == "com.inspector.SampleBuggyApp"


def test_ios_adapter_screen_size_default():
    config = Config()
    adapter = IOSAdapter(config)
    w, h = adapter.screen_size()
    assert w == 393
    assert h == 852


def test_idb_key_mapping():
    assert _idb_key("Return") == "13"
    assert _idb_key("Enter") == "13"
    assert _idb_key("Tab") == "9"
    assert _idb_key("Escape") == "27"
    assert _idb_key("Backspace") == "8"
    assert _idb_key("Space") == "32"
    assert _idb_key("a") == "a"  # unmapped key passes through


def test_shell_quote():
    assert _shell_quote("hello") == "'hello'"
    assert _shell_quote("it's") == "'it'\\''s'"
    assert _shell_quote("") == "''"


def test_macos_plane_init_with_host():
    plane = MacOSPlane(host="192.168.1.100", user="admin")
    assert plane.host == "192.168.1.100"
    assert plane.user == "admin"
    assert plane._tart_started is False


def test_macos_plane_start_skips_when_host_set():
    plane = MacOSPlane(host="192.168.1.100")
    plane.start()  # should not raise — just returns because host is already set
    assert plane.host == "192.168.1.100"
    assert plane._tart_started is False


def test_macos_plane_ssh_cmd():
    plane = MacOSPlane(host="10.0.0.5", user="testuser")
    cmd = plane._ssh_cmd("echo hello", timeout=30)
    assert "testuser@10.0.0.5" in cmd
    assert "echo hello" in cmd
    assert "-o" in cmd
    assert "StrictHostKeyChecking=no" in cmd


def test_cmd_result():
    r = _CmdResult(stdout="hello\n", returncode=0)
    assert r.stdout == "hello\n"
    assert r.returncode == 0


def test_macos_plane_stop_without_start():
    """Stop should not raise even if nothing was started."""
    plane = MacOSPlane(host="10.0.0.5")
    plane.stop()  # should be a no-op


def test_ios_adapter_teardown_without_launch():
    """Teardown should not raise even if launch was never called."""
    config = Config()
    adapter = IOSAdapter(config)
    adapter.plane.host = "10.0.0.5"  # fake host so stop doesn't try tart
    adapter.teardown()  # should not raise
