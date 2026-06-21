"""Locks the confirmed OmniParser-V2 Replicate output contract (probed live).

Output: {"img": <uri>, "elements": <string>} where elements is newline-delimited
"icon N: {python-dict-literal}" lines, bbox is ratios (0..1), dicts are single-quoted.
"""

from inspector.perception.detector import OmniParserDetector

# Verbatim sample of the real `elements` string (single-quoted python dicts).
REAL_ELEMENTS = (
    "icon 0: {'type': 'text', 'bbox': [0.319, 0.222, 0.382, 0.247], "
    "'interactivity': False, 'content': 'Your name'}\n"
    "icon 1: {'type': 'text', 'bbox': [0.500, 0.222, 0.532, 0.247], "
    "'interactivity': False, 'content': 'Save'}\n"
    "icon 2: {'type': 'icon', 'bbox': [0.302, 0.111, 0.436, 0.195], "
    "'interactivity': True, 'content': 'Settings] '}"
)


def test_parse_real_single_quoted_lines():
    items = OmniParserDetector._parse_elements(REAL_ELEMENTS)
    assert len(items) == 3
    assert items[0]["content"] == "Your name"
    assert items[2]["type"] == "icon" and items[2]["interactivity"] is True


def test_to_elements_keeps_ratios_and_indexes():
    raw = OmniParserDetector._parse_elements(REAL_ELEMENTS)
    els = OmniParserDetector._to_elements(raw)
    # index == position (Set-of-Mark id)
    assert [e.id for e in els] == [0, 1, 2]
    # ratios are preserved (no pixel normalization for this model)
    assert els[0].bbox[0] == 0.319
    assert all(0.0 <= v <= 1.0 for e in els for v in e.bbox)
    # interactivity carried through
    assert els[1].interactivity is False
    assert els[2].interactivity is True
    assert els[0].label == "Your name"


def test_pixel_fallback_normalizes_only_when_out_of_range():
    # a clearly-pixel bbox (>1.5) with no image falls back to leaving as-is (can't normalize)
    raw = [{"type": "icon", "bbox": [10, 20, 100, 200], "interactivity": True, "content": "x"}]
    els = OmniParserDetector._to_elements(raw, image_bytes=None)
    assert els[0].bbox == [10.0, 20.0, 100.0, 200.0]  # untouched without image dims
