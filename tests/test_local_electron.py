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


# --- the CDP Network channel (failed fetches / 500s / CORS are invisible without it) ---

class _NetCDP(CDPClient):
    """CDPClient with the socket removed: event correlation and the buffer are pure, so
    feeding synthetic CDP frames through the REAL `_on_event` exercises them offline."""

    def __init__(self):
        self._console: list[str] = []
        self._network: dict[str, dict] = {}
        self.commands: list[str] = []

    def _cmd(self, method, params=None):
        self.commands.append(method)
        return {}

    def _pump(self, budget: float = 0.1) -> None:
        pass


def _sent(rid, url="https://api.test/x", method="GET", ts=1.0, kind="XHR"):
    return {"method": "Network.requestWillBeSent",
            "params": {"requestId": rid, "type": kind, "timestamp": ts,
                       "request": {"url": url, "method": method}}}


def _received(rid, status=200, mime="application/json", ts=1.2, url=""):
    return {"method": "Network.responseReceived",
            "params": {"requestId": rid, "timestamp": ts,
                       "response": {"status": status, "mimeType": mime, "url": url}}}


def _finished(rid, ts=1.25):
    return {"method": "Network.loadingFinished", "params": {"requestId": rid, "timestamp": ts}}


def _failed(rid, error="net::ERR_CONNECTION_REFUSED", ts=1.4):
    return {"method": "Network.loadingFailed",
            "params": {"requestId": rid, "timestamp": ts, "errorText": error}}


def _feed(cdp, *events):
    for e in events:
        cdp._on_event(e)
    return cdp


def test_enable_turns_on_the_network_domain():
    cdp = _NetCDP()
    CDPClient.enable(cdp)
    assert "Network.enable" in cdp.commands


def test_network_correlates_four_events_into_one_record():
    cdp = _feed(_NetCDP(),
                _sent("42", url="https://api.test/items", method="POST", ts=1.0),
                _received("42", status=201, mime="application/json", ts=1.2),
                _finished("42", ts=1.5))
    recs = cdp.drain_network()
    assert len(recs) == 1
    r = recs[0]
    assert r["method"] == "POST" and r["url"] == "https://api.test/items"
    assert r["status"] == 201 and r["mime_type"] == "application/json"
    assert r["failed"] is False and r["error"] == ""
    assert r["duration_ms"] == 500          # loadingFinished wins over responseReceived
    assert "_start" not in r                # internal timing key stays internal


def test_network_records_a_server_error_and_a_dead_fetch():
    cdp = _NetCDP()
    _feed(cdp, _sent("a", url="https://api.test/boom"),
          _received("a", status=500, mime="text/html"), _finished("a"))
    _feed(cdp, _sent("b", url="https://api.test/gone"), _failed("b"))
    by_url = {r["url"]: r for r in cdp.drain_network()}
    assert by_url["https://api.test/boom"]["status"] == 500
    assert by_url["https://api.test/boom"]["failed"] is False   # it answered, badly
    dead = by_url["https://api.test/gone"]
    assert dead["failed"] is True and "ERR_CONNECTION_REFUSED" in dead["error"]
    assert dead["status"] is None and dead["duration_ms"] == 400


def test_network_keeps_a_response_whose_request_start_was_missed():
    # In flight when Network.enable ran / already drained: the failure still has to land.
    cdp = _feed(_NetCDP(), _received("z", status=502, url="https://api.test/late"))
    r = cdp.drain_network()[0]
    assert r["status"] == 502 and r["url"] == "https://api.test/late"
    assert r["method"] == "" and r["duration_ms"] is None


def test_network_buffer_is_bounded_and_evicts_successes_before_failures():
    from inspector.adapters.cdp_client import NETWORK_BUFFER_LIMIT
    cdp = _NetCDP()
    _feed(cdp, _sent("fail-1", url="https://api.test/1"), _failed("fail-1"))
    _feed(cdp, _sent("err-1", url="https://api.test/2"), _received("err-1", status=503),
          _finished("err-1"))
    for i in range(NETWORK_BUFFER_LIMIT * 3):     # a chatty app floods the buffer
        rid = f"ok-{i}"
        _feed(cdp, _sent(rid, url=f"https://cdn.test/{i}.js"), _received(rid), _finished(rid))
    recs = cdp.drain_network()
    assert len(recs) == NETWORK_BUFFER_LIMIT
    kept = {r["request_id"] for r in recs}
    assert "fail-1" in kept and "err-1" in kept   # the two records a tester needs
    assert "ok-0" not in kept                     # oldest successful noise went first


def test_drain_network_clears_like_drain_console():
    cdp = _feed(_NetCDP(), _sent("1"), _received("1"), _finished("1"))
    assert len(cdp.drain_network()) == 1
    assert cdp.drain_network() == []


def test_network_never_leaks_into_the_console_channel():
    # Double-counting guard: anything scanning logs() for errors must not also see the
    # failed request, and the console tap must keep working alongside it.
    cdp = _feed(_NetCDP(),
                {"method": "Runtime.consoleAPICalled",
                 "params": {"type": "error", "args": [{"value": "boom"}]}},
                _sent("1"), _failed("1"))
    assert cdp.drain_console() == ["[console.error] boom"]
    assert [r["failed"] for r in cdp.drain_network()] == [True]


def test_adapter_network_delegates_to_cdp_and_noops_without_one():
    from inspector.adapters.base import SurfaceAdapter
    a = _adapter(_feed(_NetCDP(), _sent("1", url="https://api.test/u"), _failed("1")))
    assert a.network()[0]["url"] == "https://api.test/u"
    a.cdp = None
    assert a.network() == []
    assert SurfaceAdapter.network(a) == []       # surfaces without traffic capture no-op


def test_get_adapter_local_vs_vm_electron():
    from inspector.adapters.electron import ElectronAdapter
    assert isinstance(get_adapter(Surface.ELECTRON, Config(execution="local")), LocalElectronAdapter)
    # The sandboxed branch needs a key now: without one get_adapter refuses up front
    # rather than failing deep inside the e2b client.
    vm = Config(execution="vm", e2b_api_key="e2b_test")
    assert isinstance(get_adapter(Surface.ELECTRON, vm), ElectronAdapter)
