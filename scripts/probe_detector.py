"""Run one real OmniParser prediction on a synthetic image to learn the exact
`elements` string format. ~$0.002, no sandbox needed.
"""

from __future__ import annotations

import io

from dotenv import load_dotenv

load_dotenv()

import replicate  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

img = Image.new("RGB", (800, 400), (245, 245, 245))
d = ImageDraw.Draw(img)
d.text((40, 40), "Settings", fill=(0, 0, 0))
d.rectangle([40, 120, 200, 170], outline=(0, 0, 0), width=2)
d.text((70, 138), "Save", fill=(0, 0, 0))
buf = io.BytesIO()
img.save(buf, format="PNG")
buf.seek(0)

VERSION = "microsoft/omniparser-v2:49cf3d41b8d3aca1360514e83be4c97131ce8f0d99abfc365526d8384caa88df"
out = replicate.run(
    VERSION,
    input={"image": buf, "imgsz": 640, "box_threshold": 0.05, "iou_threshold": 0.1},
    use_file_output=False,
)

print("output type:", type(out).__name__)
print("keys:", list(out.keys()) if hasattr(out, "keys") else "(not a dict)")
print("\nimg field:", str(out.get("img"))[:140])
el = out.get("elements")
print("\nelements field type:", type(el).__name__)
print("elements field value (first 2500 chars):\n")
print(repr(el)[:2500])
