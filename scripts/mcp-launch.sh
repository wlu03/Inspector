#!/usr/bin/env bash
# Launch the Inspector MCP server with the local toolchain on PATH, so EVERY surface
# works when a host agent (Claude Code) spawns the server with a minimal environment:
#   - web/electron/expo  -> node (Homebrew)
#   - android            -> Android SDK (adb/emulator/aapt) + JDK 17 (gradle)
#   - ios                -> Xcode (xcrun/simctl/xcodebuild) + xcodegen + idb (+companion)
# Keys are read from .env by the server itself. Edit the paths below if yours differ.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

export ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
# /opt/homebrew/bin → node, xcodegen, idb_companion; /usr/bin (inherited) → xcrun/simctl.
export PATH="/opt/homebrew/opt/openjdk@17/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:/opt/homebrew/bin:$PATH"

# iOS driver: idb lives in an isolated venv (py3.10–3.12). Point the server at it if the
# user hasn't already, so `surface="ios"` works out of the box.
if [ -z "${INSPECTOR_IDB_BIN:-}" ] && [ -x "$HOME/.idb-venv/bin/idb" ]; then
  export INSPECTOR_IDB_BIN="$HOME/.idb-venv/bin/idb"
fi

exec "$HERE/../.venv/bin/inspector" "$@"
