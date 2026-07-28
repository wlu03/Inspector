import json
import shutil
import subprocess

import pytest

from inspector.adapters import get_adapter
from inspector.adapters.base import InputAction
from inspector.adapters.cdp_client import (
    DOM_AUDIT_EXPR,
    CDPClient,
    axe_source,
    parse_dom_elements,
)
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


# --- the deterministic DOM audit on the LOCAL path (no sandbox, no browser) ---

class _AuditCDP(CDPClient):
    """CDPClient with the socket removed: `evaluate` is the only I/O the audit does,
    so overriding it exercises the real inject/parse/annotate logic offline."""

    def __init__(self, payload, axe_typeof="object", axe_present=False):
        self.payload = payload            # what the in-page audit expression returns
        self.axe_typeof = axe_typeof      # what `typeof window.axe` reports after inject
        self.axe_present = axe_present    # page already has axe (a repeat audit)
        self.exprs: list[tuple[str, bool]] = []

    def evaluate(self, expr, await_promise=False):
        self.exprs.append((expr, await_promise))
        if await_promise:
            return self.payload
        if expr == "typeof window.axe":
            return "object" if self.axe_present else "undefined"
        return self.axe_typeof


def _payload(**over):
    base = {"axe_violations": [], "broken_images": [], "unlabeled_inputs": []}
    base.update(over)
    return json.dumps(base)


def test_vendored_axe_is_bundled():
    # The whole point of vendoring: injection must not depend on the CDN (a strict
    # script-src silently blocks it and zero violations then reads as a pass).
    src = axe_source()
    assert "axe v4.10.2" in src[:200] and len(src) > 100_000


def test_audit_dom_injects_vendored_axe_then_parses():
    violation = {"id": "image-alt", "impact": "critical", "help": "h", "nodes": 2}
    cdp = _AuditCDP(_payload(axe_violations=[violation], axe_ran=True))
    out = CDPClient.audit_dom(cdp)
    assert out["axe_violations"] == [violation]
    assert "axe_error" not in out                       # axe ran → nothing to report
    inject_expr, inject_await = cdp.exprs[1]
    assert "axe v4.10.2" in inject_expr and not inject_await   # source text, not a URL
    assert cdp.exprs[2] == (DOM_AUDIT_EXPR, True)              # audit awaits the IIFE


def test_audit_dom_skips_reinjection_when_the_page_already_has_axe():
    cdp = _AuditCDP(_payload(axe_ran=True), axe_present=True)
    CDPClient.audit_dom(cdp)
    assert [e[0] for e in cdp.exprs] == ["typeof window.axe", DOM_AUDIT_EXPR]


def test_audit_dom_surfaces_axe_error_instead_of_an_empty_pass():
    # axe never defined itself (CSP-blocked CDN + no vendored copy in the page):
    # the audit must SAY so, because [] violations otherwise reads as a clean page.
    cdp = _AuditCDP(_payload(axe_error="axe-core CDN blocked (script-src CSP or no network)"),
                    axe_typeof="undefined")
    out = CDPClient.audit_dom(cdp)
    assert out["axe_violations"] == []
    assert "CDN blocked" in out["axe_error"]
    assert "window.axe" in out["axe_error"]   # plus why the vendored inject didn't take


def test_audit_dom_reports_a_silent_axe_even_when_the_page_says_nothing():
    cdp = _AuditCDP(_payload(), axe_typeof="undefined")     # no axe_ran, no axe_error
    out = CDPClient.audit_dom(cdp)
    assert out["axe_error"]                                 # never a silent empty pass


def test_audit_dom_keeps_dom_checks_when_axe_fails():
    # naturalWidth / label checks are pure DOM — an axe failure must not erase them.
    cdp = _AuditCDP(
        _payload(broken_images=["logo.png"], unlabeled_inputs=["email"], axe_error="boom"),
        axe_typeof="undefined")
    out = CDPClient.audit_dom(cdp)
    assert out["broken_images"] == ["logo.png"] and out["unlabeled_inputs"] == ["email"]
    assert out["axe_error"]


def test_audit_dom_degrades_to_empty_on_a_dead_socket():
    assert CDPClient.audit_dom(_AuditCDP(None)) == {}          # evaluate returned nothing
    assert CDPClient.audit_dom(_AuditCDP("not json")) == {}    # unparseable payload


def test_adapter_audit_dom_delegates_to_cdp_and_noops_without_one():
    a = _adapter(_AuditCDP(_payload(broken_images=["x.png"], axe_ran=True)))
    assert a.audit_dom()["broken_images"] == ["x.png"]
    a.cdp = None
    assert a.audit_dom() == {}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_shared_audit_expression_survives_an_axe_failure(tmp_path):
    """Run the REAL in-page expression under node against a DOM stub whose axe load
    fails: the pure-DOM signals must still be found, and the failure must be named."""
    stub = r"""
const inputs = [
  { type:'text', name:'email', id:'', getAttribute:() => null, closest:() => null },
  { type:'text', name:'q', id:'', getAttribute:(a) => a==='aria-label' ? 'Search' : null, closest:() => null },
];
const images = [
  { complete:true, naturalWidth:0, currentSrc:'', src:'broken.png' },
  { complete:true, naturalWidth:120, currentSrc:'', src:'ok.png' },
];
global.document = {
  images,
  querySelectorAll: (sel) => sel === 'input,select,textarea' ? inputs : [],
  createElement: () => { const el = {}; setTimeout(() => el.onerror && el.onerror(), 0); return el; },
  head: { appendChild: () => {} },
};
global.window = {};  // axe never loads
"""
    f = tmp_path / "audit_expr.cjs"
    f.write_text(stub + "\nPromise.resolve(" + DOM_AUDIT_EXPR + ").then(s => console.log(s));\n")
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["broken_images"] == ["broken.png"]
    assert out["unlabeled_inputs"] == ["email"]
    assert out["axe_violations"] == [] and not out.get("axe_ran")
    assert "axe-core" in out["axe_error"]


def test_get_adapter_local_vs_vm_electron():
    from inspector.adapters.electron import ElectronAdapter
    assert isinstance(get_adapter(Surface.ELECTRON, Config(execution="local")), LocalElectronAdapter)
    # The sandboxed branch needs a key now: without one get_adapter refuses up front
    # rather than failing deep inside the e2b client.
    vm = Config(execution="vm", e2b_api_key="e2b_test")
    assert isinstance(get_adapter(Surface.ELECTRON, vm), ElectronAdapter)
