"""One-shot diagnostic: inspect the E2B desktop environment and confirm the
real OmniParser/Replicate output schema. Spends ~1 short sandbox + 1 OmniParser run.
"""

from __future__ import annotations

import io

from dotenv import load_dotenv

load_dotenv()

from e2b_desktop import Sandbox  # noqa: E402

print("== creating sandbox ==", flush=True)
sbx = Sandbox.create(resolution=(1280, 800), timeout=300)
try:
    checks = [
        "cat /etc/os-release | head -1",
        "node --version",
        "npm --version",
        "which google-chrome chromium chromium-browser firefox",
        "which xdotool wmctrl",
        'printf "DISPLAY=%s" "$DISPLAY"',
    ]
    for cmd in checks:
        r = sbx.commands.run(cmd + " 2>&1 || true")
        out = (getattr(r, "stdout", "") or "").strip()
        print(f"$ {cmd}\n  {out}", flush=True)

    print("== screenshot ==", flush=True)
    png = bytes(sbx.screenshot())
    print("screenshot bytes:", len(png), flush=True)

    print("== OmniParser via Replicate (real call) ==", flush=True)
    import replicate

    out = replicate.run(
        "microsoft/omniparser-v2",
        input={
            "image": io.BytesIO(png),
            "imgsz": 640,
            "box_threshold": 0.05,
            "iou_threshold": 0.1,
            "use_paddleocr": True,
        },
    )
    print("output type:", type(out).__name__, flush=True)
    if isinstance(out, dict):
        print("output keys:", list(out.keys()), flush=True)
        for k, v in out.items():
            print(f"  {k}: {type(v).__name__} = {repr(v)[:300]}", flush=True)
    elif isinstance(out, (list, tuple)):
        print("list len:", len(out), flush=True)
        print("first item:", repr(out[0])[:400] if out else "(empty)", flush=True)
    else:
        print("repr:", repr(out)[:1200], flush=True)
finally:
    sbx.kill()
    print("== sandbox killed ==", flush=True)
