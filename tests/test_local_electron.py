import json

from inspector.adapters import get_adapter
from inspector.adapters.base import InputAction
from inspector.adapters.cdp_client import parse_dom_elements
from inspector.adapters.local_electron import LocalElectronAdapter
from inspector.config import Config
from inspector.models import ActionType, Surface


def test_parse_dom_elements_normalizes_to_viewport():
    raw = json.dumps([
        {"label": "Save", "role": "button", "x": 100, "y": 200, "w": 80, "h": 40},
        {"label": "Name", "role": "input", "x": 0, "y": 0, "w": 1280, "h": 30},
        {"label": "bad", "role": "div", "x": 0, "y": 0, "w": 0, "h": 0},  # degenerate → skipped
    ])
    els = parse_dom_elements(raw, 1280, 800)
    assert len(els) == 2
    assert els[0].label == "Save" and els[0].source == "dom" and els[0].interactivity
    assert abs(els[0].bbox[0] - 100 / 1280) < 1e-9 and abs(els[0].bbox[2] - 180 / 1280) < 1e-9


def test_dom_coordinate_contract():
    el = parse_dom_elements(
        json.dumps([{"label": "Save", "role": "button", "x": 100, "y": 200, "w": 80, "h": 40}]),
        1280, 800)[0]
    # center_px(viewport CSS px) lands the CDP click at the element center (140, 220)
    assert el.center_px(1280, 800) == (140, 220)


class _FakeCDP:
    def __init__(self, eval_value=None, console=None):
        self.calls = []
        self.eval_value = eval_value
        self._console = console or []

    def click(self, x, y, clicks=1): self.calls.append(("click", x, y, clicks))
    def type_text(self, t): self.calls.append(("type", t))
    def key(self, k): self.calls.append(("key", k))
    def scroll(self, x, y, dy): self.calls.append(("scroll", x, y, dy))
    def drag(self, *a): self.calls.append(("drag", *a))
    def evaluate(self, expr, await_promise=False): return self.eval_value
    def drain_console(self): return self._console
    def screenshot(self): return b"PNG"
    def enable(self): pass
    def close(self): pass


def _adapter(cdp):
    a = LocalElectronAdapter(Config())
    a.cdp = cdp
    a._viewport = (1280, 800)
    return a


def test_input_maps_to_cdp():
    a = _adapter(_FakeCDP())
    a.input(InputAction(ActionType.CLICK, x=140, y=220))
    a.input(InputAction(ActionType.TYPE, x=50, y=60, text="Alice"))
    a.input(InputAction(ActionType.KEY, key="enter"))
    calls = a.cdp.calls
    assert ("click", 140, 220, 1) in calls
    assert ("click", 50, 60, 1) in calls and ("type", "Alice") in calls  # focus then type
    assert ("key", "enter") in calls


def test_detect_elements_from_dom_then_none():
    raw = json.dumps([{"label": "A", "role": "button", "x": 10, "y": 10, "w": 80, "h": 40}])
    a = _adapter(_FakeCDP(eval_value=raw))
    els = a.detect_elements(b"PNG")
    assert els is not None and els[0].source == "dom" and els[0].label == "A"
    assert _adapter(_FakeCDP(eval_value=None)).detect_elements(b"PNG") is None  # CDP down → OmniParser


def test_screen_size_is_viewport():
    assert _adapter(_FakeCDP()).screen_size() == (1280, 800)


def test_screenshot_downscales_2x_to_css_viewport():
    # #7: Page.captureScreenshot is at devicePixelRatio (2x Retina); the adapter must
    # downscale to the CSS viewport so screenshot px == screen_size() == Input.* coords.
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1600, 1000), "white").save(buf, "PNG")  # 2x of an 800x500 viewport
    cdp = _FakeCDP()
    cdp.screenshot = lambda: buf.getvalue()
    a = _adapter(cdp)
    a._viewport = (800, 500)
    assert Image.open(io.BytesIO(a.screenshot())).size == (800, 500)


def test_logs_drains_console():
    assert _adapter(_FakeCDP(console=["[console.error] boom"])).logs() == ["[console.error] boom"]


def test_get_adapter_local_vs_vm_electron():
    from inspector.adapters.electron import ElectronAdapter
    assert isinstance(get_adapter(Surface.ELECTRON, Config(execution="local")), LocalElectronAdapter)
    assert isinstance(get_adapter(Surface.ELECTRON, Config(execution="vm")), ElectronAdapter)
