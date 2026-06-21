#!/usr/bin/env bash
# Launch the Inspector MCP server with the local toolchain on PATH, so EVERY surface
# works when a host agent (Claude Code) spawns the server with a minimal environment:
#   - web/electron/expo  -> node (Homebrew)
#   - android            -> Android SDK (adb/emulator/aapt) + JDK 17 (gradle)
#   - ios (if used)      -> set INSPECTOR_IDB_BIN / INSPECTOR_IOS_UDID in .env
# Keys are read from .env by the server itself. Edit the paths below if yours differ.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

export ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
export PATH="/opt/homebrew/opt/openjdk@17/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:/opt/homebrew/bin:$PATH"

exec "$HERE/../.venv/bin/inspector" "$@"
