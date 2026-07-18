from __future__ import annotations

import os
import sys

from .config import Config


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "XX"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _info(label: str, ok: bool, detail: str = "") -> None:
    """Report an optional/informational check — never fails the run."""
    mark = "OK" if ok else "--"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def main() -> int:
    """Preflight check: are the *required* credentials present and SDKs importable?

    Only the detector key is required (for the default `replicate` detector). E2B
    (sandbox plane) and Anthropic (autopilot brain) are optional — they only report,
    never fail the check.
    """
    print("Inspector doctor\n")
    cfg = Config.from_env()
    required_ok = True

    print("Credentials (.env / environment):")
    if cfg.detector_backend == "replicate":
        required_ok &= _check("REPLICATE_API_TOKEN set (detector)", bool(cfg.replicate_api_token))
    else:
        _info(f"detector backend = {cfg.detector_backend} (no Replicate token needed)", True)
    _info("E2B_API_KEY set (optional — only for the sandbox plane)", bool(cfg.e2b_api_key))
    _info("ANTHROPIC_API_KEY set (optional — autopilot brain)", bool(cfg.anthropic_api_key))
    print(f"\n  detector backend: {cfg.detector_backend}")
    print(f"  execution:        {cfg.execution}  (local = run on host; vm/e2b = sandbox)")
    print(f"  trace root:       {cfg.trace_root}")

    print("\nSDK imports (required):")
    for mod in ("fastmcp", "PIL", "httpx", "pydantic", "dotenv"):
        try:
            __import__(mod)
            _check(f"import {mod}", True)
        except Exception as exc:  # noqa: BLE001
            detail = (str(exc).splitlines() or ["missing"])[0]
            required_ok &= _check(f"import {mod}", False, detail)
    print("\nSDK imports (optional — only for that capability):")
    for mod, why in (("replicate", "detector"), ("e2b_desktop", "sandbox"), ("anthropic", "autopilot")):
        try:
            __import__(mod)
            _info(f"import {mod} ({why})", True)
        except Exception:  # noqa: BLE001
            _info(f"import {mod} ({why})", False, "not installed")

    print("\nExecution planes (install what your target surface needs):")
    import shutil

    from .adapters.local_web import chrome_bin
    chrome = os.path.exists(chrome_bin()) or bool(shutil.which(chrome_bin()))
    node = bool(shutil.which("node"))
    idb = (cfg.ios_idb_bin if (cfg.ios_idb_bin and "/" in cfg.ios_idb_bin)
           else shutil.which(cfg.ios_idb_bin or "idb"))
    _info("web/Electron in the E2B sandbox: E2B_API_KEY + e2b-desktop",
          bool(cfg.e2b_api_key) and _importable("e2b_desktop"))
    _info("local web: node + Chrome/Chromium", node and chrome)
    _info("local Electron: node (+ the app's own electron dependency)", node)
    _info("Android (local AVD): adb + emulator (Android SDK)",
          bool(shutil.which("adb")) and bool(shutil.which("emulator")))
    _info("Android (Redroid container): docker", bool(shutil.which("docker")))
    _info("iOS: xcrun + idb + idb_companion",
          bool(shutil.which("xcrun")) and bool(idb) and bool(shutil.which("idb_companion")),
          "" if (shutil.which("xcrun") and idb) else f"INSPECTOR_IDB_BIN={cfg.ios_idb_bin}")
    _info("macOS/iOS VM: tart (or set INSPECTOR_MACOS_HOST for a remote Mac)",
          bool(shutil.which("tart")) or bool(cfg.macos_host))
    _info("macOS native app: this host + Accessibility permission",
          sys.platform == "darwin")

    print()
    if required_ok:
        print("All required checks passed. Start the server with: inspector-mcp serve")
    else:
        print("Some required checks failed — fix the above, then re-run: inspector-mcp doctor")
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
