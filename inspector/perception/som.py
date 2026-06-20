from __future__ import annotations

import io

from ..models import Element


def render_set_of_mark(image_bytes: bytes, elements: list[Element]) -> bytes:
    """Draw numbered boxes (Set-of-Mark) over the screenshot.

    The host agent reads the numbers and picks an element id; the action
    dispatcher maps that id back to the element's bbox center.
    """
    from PIL import Image, ImageDraw, ImageFont  # lazy (pillow)

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - font always present in practice
        font = None

    for el in elements:
        bx = (el.bbox + [0, 0, 0, 0])[:4]
        if max(bx) <= 1.5:  # ratios -> pixels
            bx = [bx[0] * width, bx[1] * height, bx[2] * width, bx[3] * height]
        x1, y1, x2, y2 = bx
        color = (255, 0, 0) if el.interactivity else (0, 128, 255)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)

        label = str(el.id)
        if font is not None:
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        else:  # pragma: no cover
            tw, th = 8 * len(label), 12
        draw.rectangle([x1, y1 - th - 4, x1 + tw + 4, y1], fill=color)
        draw.text((x1 + 2, y1 - th - 3), label, fill="white", font=font)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
