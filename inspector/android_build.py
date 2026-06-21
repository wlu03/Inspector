from __future__ import annotations

import glob
import os
import re
import subprocess
from dataclasses import dataclass

from .planes.android import _sdk_root
from .source_scan import detect_framework


@dataclass
class BuildResult:
    apk_path: str
    package: str
    activity: str


# --- pure helpers (unit-tested, no toolchain) ---

def resolve_framework(repo_path: str) -> str:
    """'flutter' | 'react-native' | 'native'. RN/Flutter come from the manifest;
    a bare gradle project is native."""
    fw = detect_framework(repo_path)
    if fw in ("flutter", "react-native"):
        return fw
    return "native"


def android_build_commands(framework: str) -> list[str]:
    """Shell commands (run in the project dir) that produce a DEBUG apk. Pure.

    Each runs sequentially; the second can `cd` because each is its own shell.
    """
    if framework == "flutter":
        return ["flutter build apk --debug"]
    if framework == "react-native":
        # install deps first (a fresh repo has no node_modules); Expo projects have no
        # android/ until prebuild generates it; bare RN already does (|| true).
        return [
            "npm install",
            "npx expo prebuild -p android --no-install || true",
            "cd android && ./gradlew assembleDebug",
        ]
    # native: gradle wrapper at the repo root
    return ["./gradlew assembleDebug"]


def apk_glob_patterns(framework: str) -> list[str]:
    """Where the debug APK lands per framework, relative to the project dir. Pure."""
    if framework == "flutter":
        return ["build/app/outputs/flutter-apk/app-debug.apk"]
    return [
        "android/app/build/outputs/apk/debug/*.apk",  # RN/Expo
        "app/build/outputs/apk/debug/*.apk",          # native
        "**/build/outputs/apk/**/*[dD]ebug*.apk",     # fallback
    ]


# Build intermediates / test APKs that must never be installed as "the app".
_APK_EXCLUDE = ("androidtest", "unaligned", "unsigned")


def pick_newest(paths: list[str]) -> str | None:
    """Newest existing, installable APK by mtime. Pure-ish (stats files).

    Excludes instrumentation/intermediate variants (e.g. app-debug-androidTest.apk)
    that share the `*debug*` glob but must not be installed as the app.
    """
    existing = [
        p for p in paths
        if os.path.isfile(p) and not any(x in os.path.basename(p).lower() for x in _APK_EXCLUDE)
    ]
    if not existing:
        return None
    return max(existing, key=os.path.getmtime)


def parse_aapt_badging(out: str) -> tuple[str | None, str | None]:
    """(package, launchable-activity) from `aapt dump badging <apk>`. Pure."""
    pkg = re.search(r"package: name='([^']+)'", out or "")
    act = re.search(r"launchable-activity: name='([^']+)'", out or "")
    return (pkg.group(1) if pkg else None), (act.group(1) if act else None)


# --- the builder ---

class AndroidBuilder:
    """Build a debug APK from source, locally (gradle / expo prebuild / flutter),
    and resolve its package + launch activity via aapt. Heavy/slow → generous
    timeouts; the host needs JDK 17 + the Android SDK build-tools."""

    def __init__(self, config):
        self.config = config

    def build(self, repo_path: str) -> BuildResult:
        framework = resolve_framework(repo_path)
        for cmd in android_build_commands(framework):
            self._run(cmd, cwd=repo_path)
        apk = self._find_apk(repo_path, framework)
        if not apk:
            raise RuntimeError(f"no debug APK found after building {repo_path!r} ({framework})")
        package, activity = self._badging(apk)
        if not package or not activity:
            raise RuntimeError(f"could not resolve package/activity from {apk!r}")
        return BuildResult(apk_path=apk, package=package, activity=activity)

    # --- internals (shell out to the toolchain) ---
    def _run(self, cmd: str, cwd: str, timeout: int = 1800) -> None:
        proc = subprocess.run(
            cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-800:]
            raise RuntimeError(f"build step failed: {cmd}\n{tail}")

    def _find_apk(self, repo_path: str, framework: str) -> str | None:
        # Prefer specific patterns over the broad fallback: take the first pattern
        # that yields an installable APK, so a stray intermediate matched only by the
        # `**` fallback never wins on mtime over the real app/debug output.
        for pattern in apk_glob_patterns(framework):
            hit = pick_newest(glob.glob(os.path.join(repo_path, pattern), recursive=True))
            if hit:
                return hit
        return None

    def _badging(self, apk: str) -> tuple[str | None, str | None]:
        out = subprocess.run(
            [self._aapt_bin(), "dump", "badging", apk], capture_output=True, text=True
        ).stdout
        return parse_aapt_badging(out)

    def _aapt_bin(self) -> str:
        # newest build-tools/<ver>/aapt under the SDK; fall back to PATH.
        tools = sorted(glob.glob(os.path.join(_sdk_root(), "build-tools", "*", "aapt")))
        return tools[-1] if tools else "aapt"
