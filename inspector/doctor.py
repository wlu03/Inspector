from __future__ import annotations

from .config import Config


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "OK" if ok else "XX"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    """Preflight check: are the credentials present and the SDKs importable?"""
    print("Inspector doctor\n")
    cfg = Config.from_env()
    required_ok = True

    print("Credentials (.env / environment):")
    required_ok &= _check("E2B_API_KEY set", bool(cfg.e2b_api_key))
    required_ok &= _check("REPLICATE_API_TOKEN set", bool(cfg.replicate_api_token))
    _check("ANTHROPIC_API_KEY set (optional)", bool(cfg.anthropic_api_key))
    print(f"\n  detector backend: {cfg.detector_backend}")
    print(f"  trace root:       {cfg.trace_root}")

    print("\nSDK imports:")
    for mod in ("fastmcp", "e2b_desktop", "replicate", "PIL", "httpx", "pydantic", "dotenv"):
        try:
            __import__(mod)
            _check(f"import {mod}", True)
        except Exception as exc:  # noqa: BLE001
            detail = (str(exc).splitlines() or ["missing"])[0]
            required_ok &= _check(f"import {mod}", False, detail)

    print()
    if required_ok:
        print("All required checks passed. Run the server with: python -m inspector.server")
    else:
        print("Some required checks failed — fix the above, then re-run python -m inspector.doctor")
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
