"""AndroidAdapter attach mode: drive an already-installed app on a running emulator."""
from __future__ import annotations

from types import SimpleNamespace

from inspector.adapters.android import (
    AndroidAdapter,
    first_device_serial,
    resolve_component,
)


# --- pure parsing helpers ---

def test_first_device_serial_picks_ready_device():
    out = ("List of devices attached\n"
           "emulator-5554\tdevice\n"
           "emulator-5556\toffline\n")
    assert first_device_serial(out) == "emulator-5554"


def test_first_device_serial_none_when_no_device():
    assert first_device_serial("List of devices attached\n\n") is None
    assert first_device_serial("") is None


def test_resolve_component_takes_the_component_line():
    out = "priority=0 preferredOrder=0\n  com.superproductivity.superproductivity/.FullscreenActivity"
    assert resolve_component(out) == "com.superproductivity.superproductivity/.FullscreenActivity"


def test_resolve_component_none_when_absent():
    assert resolve_component("No activity found") is None
    assert resolve_component("") is None


# --- attach launch (faked adb, no device) ---

class _FakeAdb:
    def __init__(self):
        self.cmds: list[str] = []

    def shell(self, cmd, timeout=60):
        self.cmds.append(cmd)
        if "resolve-activity" in cmd:
            return "priority=0\n  com.x.app/.MainActivity"
        return ""

    def wait_for_device(self, timeout=120):
        self.cmds.append("wait-for-device")

    def install(self, *a, **k):
        self.cmds.append("install")  # must NOT happen in attach mode


def _cfg(**kw):
    base = dict(android_package=None, android_activity=None, android_serial=None,
                android_avd=None, android_runtime="local")
    base.update(kw)
    return SimpleNamespace(**base)


def test_attach_skips_build_and_starts_given_activity():
    adb = _FakeAdb()
    cfg = _cfg(android_package="com.x.app", android_serial="emulator-5554",
               android_activity="com.x.app/.Main")
    a = AndroidAdapter(cfg, adb=adb)
    a.launch("/repo")  # would import the (unimplemented) AndroidBuilder if not attach

    assert a.package == "com.x.app"
    assert any("am start -n com.x.app/.Main" in c for c in adb.cmds)
    assert "logcat -c" in adb.cmds
    assert any("svc power stayon" in c for c in adb.cmds)   # _wake ran
    assert "install" not in adb.cmds                         # no build/install
    assert a.plane is None                                   # attached, didn't boot an AVD


def test_attach_resolves_activity_when_not_configured():
    adb = _FakeAdb()
    cfg = _cfg(android_package="com.x.app", android_serial="emulator-5554")
    a = AndroidAdapter(cfg, adb=adb)
    a.launch("/repo")

    assert a.activity == "com.x.app/.MainActivity"           # resolved via cmd package
    assert any("am start -n com.x.app/.MainActivity" in c for c in adb.cmds)


def test_attach_falls_back_to_monkey_without_activity():
    adb = _FakeAdb()
    adb.shell = lambda cmd, timeout=60: adb.cmds.append(cmd) or ""  # resolve returns ""
    cfg = _cfg(android_package="com.x.app", android_serial="emulator-5554")
    a = AndroidAdapter(cfg, adb=adb)
    a.launch("/repo")
    assert any("monkey -p com.x.app" in c for c in adb.cmds)
