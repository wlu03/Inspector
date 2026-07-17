from __future__ import annotations

from .config import Config


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "XX"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _info(label: str, ok: bool, detail: str = "") -> None:
    """Report an optional/informational check — never fails the run."""
    mark = "OK" if ok else "--"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


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

    print("\nSurface toolchains (optional — only needed for that surface):")
    import shutil
    _info("node (web/electron)", bool(shutil.which("node")))
    _info("adb + emulator (android)",
          bool(shutil.which("adb")) and bool(shutil.which("emulator")))
    idb = (cfg.ios_idb_bin if (cfg.ios_idb_bin and "/" in cfg.ios_idb_bin)
           else shutil.which(cfg.ios_idb_bin or "idb"))
    ios_ok = bool(shutil.which("xcrun")) and bool(idb) and bool(shutil.which("idb_companion"))
    _info("xcrun + idb + idb_companion (ios)", ios_ok,
          "" if ios_ok else f"INSPECTOR_IDB_BIN={cfg.ios_idb_bin}")

    print()
    if required_ok:
        print("All required checks passed. Start the server with: inspector-mcp serve")
    else:
        print("Some required checks failed — fix the above, then re-run: inspector-mcp doctor")
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
