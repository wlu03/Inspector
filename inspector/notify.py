"""Best-effort OS desktop notification when an autonomous run finishes.

Autonomous/CI runs have nobody watching the chat — a desktop ping with the
dashboard link closes that gap. Pure-stdlib, fully guarded: an unsupported platform
or a missing binary just no-ops. `notify_command` is split out (pure) so it's
unit-testable without actually firing a notification.
"""

from __future__ import annotations

import platform
import shutil
import subprocess


def notify_command(title: str, message: str) -> list[str] | None:
    """The argv to fire a desktop notification on this OS, or None if unsupported."""
    system = platform.system()
    if system == "Darwin":
        safe_t = title.replace('"', "'")
        safe_m = message.replace('"', "'")
        script = f'display notification "{safe_m}" with title "{safe_t}"'
        return ["osascript", "-e", script]
    if system == "Linux" and shutil.which("notify-send"):
        return ["notify-send", title, message]
    if system == "Windows" and shutil.which("msg"):
        return ["msg", "*", f"{title}: {message}"]
    return None


def notify(title: str, message: str, enabled: bool = True) -> bool:
    """Fire a desktop notification; return True if it was dispatched. Never raises."""
    if not enabled:
        return False
    cmd = notify_command(title, message)
    if not cmd or not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(cmd, capture_output=True, timeout=5)
        return True
    except Exception:
        return False
