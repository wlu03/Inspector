"""Unit tests for the Android adapter and RedroidRuntime (no VM required)."""
from inspector.adapters.android import AndroidAdapter, _android_keycode
from inspector.config import Config
from inspector.models import Surface


def test_android_adapter_surface():
    assert AndroidAdapter.surface == Surface.ANDROID


def test_android_adapter_init():
    config = Config()
    adapter = AndroidAdapter(config)
    assert adapter.redroid is None
    assert adapter.package is None
    assert adapter._screen_w == 1080
    assert adapter._screen_h == 1920


def test_android_adapter_screen_size_default():
    config = Config()
    adapter = AndroidAdapter(config)
    assert adapter.screen_size() == (1080, 1920)


def test_android_keycode_mapping():
    assert _android_keycode("Return") == "66"
    assert _android_keycode("Enter") == "66"
    assert _android_keycode("Tab") == "61"
    assert _android_keycode("Escape") == "111"
    assert _android_keycode("Backspace") == "67"
    assert _android_keycode("Space") == "62"
    assert _android_keycode("Home") == "3"
    assert _android_keycode("Back") == "4"
    assert _android_keycode("Up") == "19"
    assert _android_keycode("a") == "a"  # unmapped passes through


def test_android_adapter_teardown_without_launch():
    """Teardown should not raise even if launch was never called."""
    config = Config()
    adapter = AndroidAdapter(config)
    adapter.teardown()  # should not raise


def test_redroid_runtime_init():
    from inspector.planes.android import RedroidRuntime
    from unittest.mock import MagicMock

    plane = MagicMock()
    rt = RedroidRuntime(plane, serial="localhost:5555", width=1080, height=1920)
    assert rt.serial == "localhost:5555"
    assert rt.width == 1080
    assert rt.height == 1920
    assert rt.plane is plane


def test_redroid_runtime_stop():
    from inspector.planes.android import RedroidRuntime
    from unittest.mock import MagicMock

    plane = MagicMock()
    rt = RedroidRuntime(plane)
    rt.stop()
    # Should call disconnect + docker rm
    assert plane.run_sync.call_count == 2
