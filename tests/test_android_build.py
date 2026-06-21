"""Pure tests for AndroidBuilder helpers — no toolchain, no device."""
from __future__ import annotations

import json

from inspector.android_build import (
    android_build_commands,
    apk_glob_patterns,
    parse_aapt_badging,
    pick_newest,
    resolve_framework,
)


# --- framework resolution ---

def test_resolve_native_when_no_manifest(tmp_path):
    (tmp_path / "build.gradle").write_text("")
    assert resolve_framework(str(tmp_path)) == "native"


def test_resolve_expo_is_react_native(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"expo": "~52"}}))
    assert resolve_framework(str(tmp_path)) == "react-native"


def test_resolve_flutter(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("dependencies:\n  flutter:\n")
    assert resolve_framework(str(tmp_path)) == "flutter"


# --- build commands per framework ---

def test_native_build_command():
    assert android_build_commands("native") == ["./gradlew assembleDebug"]


def test_react_native_installs_prebuilds_then_assembles():
    cmds = android_build_commands("react-native")
    assert cmds[0] == "npm install"
    assert any("expo prebuild -p android" in c for c in cmds)
    assert any("gradlew assembleDebug" in c for c in cmds)


def test_flutter_build_command():
    assert android_build_commands("flutter") == ["flutter build apk --debug"]


# --- apk discovery ---

def test_apk_globs_cover_rn_and_native():
    pats = apk_glob_patterns("react-native")
    assert any("android/app/build/outputs/apk/debug" in p for p in pats)
    assert any("app/build/outputs/apk/debug" in p for p in pats)


def test_flutter_apk_glob():
    assert apk_glob_patterns("flutter") == ["build/app/outputs/flutter-apk/app-debug.apk"]


def test_pick_newest(tmp_path):
    old = tmp_path / "old.apk"
    new = tmp_path / "new.apk"
    old.write_text("a")
    new.write_text("b")
    os_utime_newer(new, old)
    assert pick_newest([str(old), str(new), str(tmp_path / "missing.apk")]) == str(new)


def test_pick_newest_none_when_absent():
    assert pick_newest(["/nope/a.apk"]) is None


# --- aapt badging parse ---

def test_parse_aapt_badging():
    out = (
        "package: name='com.inspector.app' versionCode='1'\n"
        "launchable-activity: name='com.inspector.app.MainActivity'  label='App'\n"
    )
    assert parse_aapt_badging(out) == ("com.inspector.app", "com.inspector.app.MainActivity")


def test_parse_aapt_badging_missing():
    assert parse_aapt_badging("nothing useful") == (None, None)


# --- helper ---

def os_utime_newer(newer, older):
    import os
    t = os.path.getmtime(str(older))
    os.utime(str(newer), (t + 10, t + 10))
