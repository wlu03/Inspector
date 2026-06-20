import io

from loopback.perception.detector import OmniParserDetector


def _png(w, h):
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(b, format="PNG")
    return b.getvalue()


def test_ratio_bboxes_pass_through():
    raw = [{"type": "icon", "bbox": [0.1, 0.1, 0.3, 0.2], "content": "Save", "interactivity": True}]
    els = OmniParserDetector._to_elements(raw)
    assert els[0].bbox == [0.1, 0.1, 0.3, 0.2]
    assert els[0].interactivity is True
    assert els[0].label == "Save"


def test_pixel_bboxes_normalized_to_ratios():
    raw = [{"type": "icon", "bbox": [80, 40, 160, 80], "content": "Save"}]
    els = OmniParserDetector._to_elements(raw, _png(800, 400))
    assert abs(els[0].bbox[0] - 0.1) < 1e-6
    assert abs(els[0].bbox[1] - 0.1) < 1e-6
    assert abs(els[0].bbox[2] - 0.2) < 1e-6
    assert abs(els[0].bbox[3] - 0.2) < 1e-6


def test_malformed_bbox_does_not_crash():
    raw = [{"type": "text", "bbox": [1, 2]}, {"type": "text", "bbox": "oops"}, {"type": "text"}]
    els = OmniParserDetector._to_elements(raw)
    assert len(els) == 3
    for e in els:
        assert len(e.bbox) == 4
