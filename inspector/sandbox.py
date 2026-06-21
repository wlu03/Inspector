from __future__ import annotations

import os

from .config import Config


class E2BSandbox:
    """Thin wrapper over `e2b_desktop.Sandbox` (lazy-imported).

    Used by the Linux-plane adapters (web, Electron). Mirrors the exact E2B
    Desktop method names verified in docs/11 (note `move_mouse`, not `mouse_move`).
    """

    def __init__(self, config: Config):
        self.config = config
        self._sbx = None
        self._handles: list = []
        self._log_buffer: list[str] = []

    # --- lifecycle ---
    def start(self) -> None:
        from e2b_desktop import Sandbox  # lazy

        kwargs = dict(
            resolution=self.config.sandbox_resolution,
            timeout=self.config.sandbox_timeout_s,
        )
        if self.config.sandbox_template:  # custom template (e.g. one with chrome baked in)
            kwargs["template"] = self.config.sandbox_template
        self._sbx = Sandbox.create(**kwargs)
        self._sbx.stream.start()

    def keep_alive(self) -> None:
        if self._sbx:
            self._sbx.set_timeout(self.config.sandbox_timeout_s)

    def stream_url(self) -> str | None:
        return self._sbx.stream.get_url() if self._sbx else None

    def kill(self) -> None:
        for h in self._handles:
            try:
                h.kill()
            except Exception:
                pass
        self._handles.clear()
        if self._sbx is not None:
            try:
                self._sbx.kill()
            except Exception:
                pass
            finally:
                self._sbx = None

    # --- files + processes ---
    _SKIP_DIRS = {
        "node_modules", ".git", "dist", "build", ".next", ".venv", "venv",
        "coverage", ".pytest_cache", "__pycache__", ".turbo", ".cache",
    }
    _MAX_FILE_BYTES = 8 * 1024 * 1024

    def upload_dir(self, local_path: str, remote_path: str = "/home/user/app") -> None:
        for root, dirs, files in os.walk(local_path):
            dirs[:] = [d for d in dirs if d not in self._SKIP_DIRS]
            for name in files:
                if name == ".env" or name.startswith(".env."):
                    continue  # don't ship secrets into the sandbox
                lp = os.path.join(root, name)
                try:
                    if os.path.getsize(lp) > self._MAX_FILE_BYTES:
                        continue
                    rel = os.path.relpath(lp, local_path)
                    with open(lp, "rb") as fh:
                        self._sbx.files.write(f"{remote_path}/{rel}", fh.read())
                except Exception:
                    continue  # skip an unreadable file rather than abort the whole upload

    def write_file(self, path: str, content: str | bytes) -> None:
        self._sbx.files.write(path, content)

    def _on_log(self, chunk: str) -> None:
        self._log_buffer.append(chunk)

    def run_dev(self, cmd: str, cwd: str = "/home/user/app", envs: dict | None = None):
        """Start the dev server as a background process, streaming logs to the buffer."""
        handle = self._sbx.commands.run(
            cmd, background=True, cwd=cwd, envs=envs or {},
            on_stdout=self._on_log, on_stderr=self._on_log,
        )
        self._handles.append(handle)
        return handle

    def run_bg(self, cmd: str, cwd: str = "/home/user/app"):
        """Start an auxiliary background process (e.g. the browser)."""
        handle = self._sbx.commands.run(
            cmd, background=True, cwd=cwd,
            on_stdout=self._on_log, on_stderr=self._on_log,
        )
        self._handles.append(handle)
        return handle

    def run_sync(self, cmd: str, timeout: int = 30):
        """Run a foreground command and return its CommandResult (stdout/exit_code).

        Returns None on error so callers can poll without try/except everywhere.
        """
        try:
            return self._sbx.commands.run(cmd, timeout=timeout)
        except Exception:
            return None

    def drain_logs(self) -> list[str]:
        out = self._log_buffer[:]
        self._log_buffer.clear()
        return out

    # --- computer use (exact E2B Desktop method names) ---
    def screenshot(self) -> bytes:
        return bytes(self._sbx.screenshot())

    def left_click(self, x: int, y: int) -> None:
        self._sbx.left_click(x, y)

    def double_click(self, x: int, y: int) -> None:
        self._sbx.double_click(x, y)

    def move_mouse(self, x: int, y: int) -> None:
        self._sbx.move_mouse(x, y)

    def drag(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        self._sbx.drag(a, b)

    def scroll(self, direction: str = "down", amount: int = 3) -> None:
        self._sbx.scroll(direction=direction, amount=amount)

    def write(self, text: str) -> None:
        self._sbx.write(text)

    def press(self, key: str) -> None:
        self._sbx.press(key)

    def screen_size(self) -> tuple[int, int]:
        return tuple(self._sbx.get_screen_size())
