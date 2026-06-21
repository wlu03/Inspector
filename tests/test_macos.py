import json

from inspector.adapters.macos_native import _KEYCODES, ax_interactive, parse_ax_dump


def _dump(window, elements):
    return json.dumps({"pid": 1, "window": window, "elements": elements})


def test_parse_ax_dump_normalizes_to_window_ratios():
    raw = _dump({"x": 100, "y": 200, "w": 200, "h": 400}, [
        {"role": "AXButton", "label": "7", "value": "", "x": 120, "y": 260, "w": 40, "h": 40},
        {"role": "AXStaticText", "label": "", "value": "0", "x": 110, "y": 210, "w": 80, "h": 30},
        {"role": "AXGroup", "label": "", "value": "", "x": 100, "y": 200, "w": 200, "h": 400},
    ])
    win, els = parse_ax_dump(raw)
    assert win["w"] == 200
    labels = {e.label for e in els}
    assert "7" in labels and "0" in labels         # button + labeled display kept
    assert all(e.role != "group" for e in els)     # empty container dropped
    btn = next(e for e in els if e.label == "7")
    # x: (120-100)/200=0.1 .. (160-100)/200=0.3 ; y: (260-200)/400=0.15 .. 0.25
    assert abs(btn.bbox[0] - 0.1) < 1e-6 and abs(btn.bbox[2] - 0.3) < 1e-6
    assert btn.interactivity and btn.source == "ax"
    # center_px with the window POINT size maps the ratio back to a window point
    assert btn.center_px(200, 400) == (40, 80)


def test_parse_ax_dump_handles_garbage_and_no_window():
    assert parse_ax_dump("nonsense") == ({}, [])
    assert parse_ax_dump(json.dumps({"window": {}, "elements": []})) == ({}, [])


def test_ax_interactive_and_keycodes():
    assert ax_interactive("AXButton") and ax_interactive("AXTextField")
    assert not ax_interactive("AXStaticText") and not ax_interactive("AXGroup")
    assert _KEYCODES["return"] == 36 and _KEYCODES["escape"] == 53 and _KEYCODES["tab"] == 48
