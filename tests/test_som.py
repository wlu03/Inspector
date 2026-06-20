import io

from inspector.models import Element
from inspector.perception.som import render_set_of_mark


def _blank_png(w=200, h=120) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(out, format="PNG")
    return out.getvalue()


def test_render_set_of_mark_returns_png():
    elements = [
        Element(id=0, label="Save", role="icon", bbox=[0.1, 0.1, 0.3, 0.2], interactivity=True),
        Element(id=1, label="title", role="text", bbox=[0.1, 0.0, 0.9, 0.08]),
    ]
    out = render_set_of_mark(_blank_png(), elements)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    assert len(out) > 0
