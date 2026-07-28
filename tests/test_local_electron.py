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
    origin_of,
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


# --- navigation + viewport (routes and responsive layouts are unreachable without them) ---

class _DeadSocket:
    """A socket nothing ever arrives on — `_wait_for_load` must give up, never hang."""

    def settimeout(self, t): pass
    def recv(self): raise OSError("no frames")


class _NavCDP(CDPClient):
    """CDPClient with the socket swapped for canned command replies, so the REAL
    navigate/history/emulation logic (and its load-event wait) runs offline."""

    def __init__(self, history=None, replies=None, fires_load=True):
        self._ws = _DeadSocket()
        self._console: list[str] = []
        self._network: dict[str, dict] = {}
        self._load_count = 0
        self._timeout = 1
        self.sent: list[tuple[str, dict]] = []
        self.history = history
        self.replies = replies or {}
        self.fires_load = fires_load

    def _cmd_raw(self, method, params=None):
        self.sent.append((method, params or {}))
        if self.fires_load and method in (
                "Page.navigate", "Page.reload", "Page.navigateToHistoryEntry"):
            self._load_count += 1          # the page finished loading while we waited
        if method in self.replies:
            return self.replies[method]
        if method == "Page.getNavigationHistory" and self.history is not None:
            return {"result": self.history}
        return {"result": {}}

    def methods(self):
        return [m for m, _ in self.sent]


def _hist(index, urls):
    return {"currentIndex": index, "entries": [{"id": i + 1, "url": u}
                                               for i, u in enumerate(urls)]}


def test_navigate_sends_the_url_and_waits_for_the_load_event():
    cdp = _NavCDP()
    assert cdp.navigate("http://localhost:3000/does-not-exist") is True
    assert ("Page.navigate", {"url": "http://localhost:3000/does-not-exist"}) in cdp.sent
    assert cdp._load_count == 1        # waited on the event, not on a blind sleep


def test_navigate_reports_a_navigation_the_browser_refused():
    # errorText = the browser would not go there at all. A 404 from a server that DID
    # answer is a successful navigation (its status shows up on the network channel).
    cdp = _NavCDP(replies={"Page.navigate":
                           {"result": {"frameId": "1", "errorText": "net::ERR_NAME_NOT_RESOLVED"}}})
    assert cdp.navigate("http://nope.invalid/") is False


def test_navigate_is_false_on_a_dead_socket_and_on_an_empty_url():
    assert _NavCDP(replies={"Page.navigate": {}}).navigate("http://a/") is False
    cdp = _NavCDP()
    assert cdp.navigate("") is False
    assert cdp.sent == []


def test_navigate_still_reports_true_when_the_load_event_never_arrives():
    # A slow page has still navigated; the caller should go look at it rather than be
    # told the navigation failed. The wait must time out instead of blocking forever.
    cdp = _NavCDP(fires_load=False)
    assert cdp.navigate("http://localhost:3000/slow", timeout=0.05) is True


def test_back_and_forward_re_enter_the_neighbouring_history_entry():
    back = _NavCDP(history=_hist(1, ["http://a/", "http://a/items", "http://a/items/1"]))
    assert back.back() is True
    assert ("Page.navigateToHistoryEntry", {"entryId": 1}) in back.sent
    fwd = _NavCDP(history=_hist(1, ["http://a/", "http://a/items", "http://a/items/1"]))
    assert fwd.forward() is True
    assert ("Page.navigateToHistoryEntry", {"entryId": 3}) in fwd.sent


def test_history_ends_are_reported_instead_of_dispatching_a_no_op():
    # Running off the end must be visible: a silent no-op reads to the caller as a
    # successful back navigation, and the "back keeps state coherent" check then passes
    # without ever having gone back.
    start = _NavCDP(history=_hist(0, ["http://a/"]))
    assert start.back() is False
    assert "Page.navigateToHistoryEntry" not in start.methods()
    end = _NavCDP(history=_hist(1, ["http://a/", "http://a/items"]))
    assert end.forward() is False
    assert "Page.navigateToHistoryEntry" not in end.methods()


def test_history_step_is_false_without_a_usable_history():
    assert _NavCDP().back() is False            # dead socket / Page domain says nothing


def test_reload_waits_for_the_document_to_come_back():
    cdp = _NavCDP()
    assert cdp.reload() is True
    assert "Page.reload" in cdp.methods() and cdp._load_count == 1


def test_current_url_reads_the_history_not_the_page():
    # A browser-side fact, so it survives a page whose JS threw or whose CSP is strict.
    cdp = _NavCDP(history=_hist(1, ["http://a/", "http://a/items"]))
    assert cdp.current_url() == "http://a/items"
    assert "Runtime.evaluate" not in cdp.methods()


def test_current_url_falls_back_to_the_page_then_to_empty():
    cdp = _NavCDP(replies={"Runtime.evaluate": {"result": {"result": {"value": "http://a/x"}}}})
    assert cdp.current_url() == "http://a/x"
    assert _NavCDP().current_url() == ""


def test_set_viewport_overrides_device_metrics_at_scale_factor_one():
    cdp = _NavCDP()
    assert cdp.set_viewport(375, 667, mobile=True) is True
    # deviceScaleFactor 1 keeps screenshot px == CSS px == Input.* coords.
    assert ("Emulation.setDeviceMetricsOverride",
            {"width": 375, "height": 667, "deviceScaleFactor": 1, "mobile": True}) in cdp.sent
    assert ("Emulation.setTouchEmulationEnabled",
            {"enabled": True, "maxTouchPoints": 1}) in cdp.sent


def test_set_viewport_refuses_a_nonsense_size_and_a_refusing_target():
    cdp = _NavCDP()
    assert cdp.set_viewport(0, 800) is False and cdp.set_viewport(375, -1) is False
    assert cdp.sent == []
    refused = _NavCDP(replies={"Emulation.setDeviceMetricsOverride":
                               {"error": {"message": "not supported"}}})
    assert refused.set_viewport(375, 667) is False
    assert "Emulation.setTouchEmulationEnabled" not in refused.methods()


def test_clear_viewport_override_drops_the_emulation():
    cdp = _NavCDP()
    assert cdp.clear_viewport_override() is True
    assert "Emulation.clearDeviceMetricsOverride" in cdp.methods()
    assert ("Emulation.setTouchEmulationEnabled",
            {"enabled": False, "maxTouchPoints": 0}) in cdp.sent


class _NavCDPStub:
    """Adapter-facing fake: records what the adapter asked the CDP client to do."""

    def __init__(self, url="http://localhost:3000/", ok=True):
        self.url = url
        self.ok = ok
        self.eval_value = json.dumps([1280, 800])
        self.navigated: list[str] = []
        self.viewports: list[tuple[int, int, bool]] = []
        self.calls: list[str] = []
        self.cleared = 0

    def current_url(self): return self.url
    def evaluate(self, expr, await_promise=False): return self.eval_value

    def _record(self, name):
        self.calls.append(name)
        return self.ok

    def back(self): return self._record("back")
    def forward(self): return self._record("forward")
    def reload(self): return self._record("reload")

    def navigate(self, url):
        self.navigated.append(url)
        return self.ok

    def set_viewport(self, width, height, mobile=False):
        self.viewports.append((width, height, mobile))
        return self.ok

    def clear_viewport_override(self):
        self.cleared += 1
        return self.ok


def test_adapter_navigation_reports_that_it_cannot_rather_than_no_opping():
    from inspector.adapters.base import SurfaceAdapter
    a = _adapter(_NavCDPStub())
    a.cdp = None
    assert a.navigate("/x") is False and a.go_back() is False and a.go_forward() is False
    assert a.reload() is False and a.set_viewport(375, 667) is False
    # a surface with no navigation at all inherits the same falsy answer
    assert SurfaceAdapter.navigate(a, "/x") is False
    assert SurfaceAdapter.go_back(a) is False and SurfaceAdapter.go_forward(a) is False
    assert SurfaceAdapter.reload(a) is False and SurfaceAdapter.set_viewport(a, 375, 667) is False


def test_adapter_resolves_a_route_against_the_current_document():
    a = _adapter(_NavCDPStub(url="http://localhost:3000/items"))
    assert a.navigate("/does-not-exist") is True
    assert a.cdp.navigated == ["http://localhost:3000/does-not-exist"]
    assert a.go_back() and a.go_forward() and a.reload()
    assert a.cdp.calls == ["back", "forward", "reload"]


def test_navigate_refuses_to_replace_a_file_url_app_shell(monkeypatch):
    # Page.navigate on a packaged Electron shell REPLACES the app: '/does-not-exist'
    # resolves to file:///does-not-exist, the window blanks, and the router that could
    # have routed back is gone with the document. Refuse loudly instead of doing it.
    monkeypatch.delenv("INSPECTOR_ALLOW_ELECTRON_NAVIGATE", raising=False)
    a = _adapter(_NavCDPStub(url="file:///Users/x/app/dist/index.html"))
    assert a.navigate("/does-not-exist") is False
    assert a.cdp.navigated == []


def test_a_hash_route_stays_inside_the_app_shell(monkeypatch):
    monkeypatch.delenv("INSPECTOR_ALLOW_ELECTRON_NAVIGATE", raising=False)
    a = _adapter(_NavCDPStub(url="file:///Users/x/app/dist/index.html#/home"))
    assert a.navigate("#/does-not-exist") is True
    assert a.cdp.navigated == ["file:///Users/x/app/dist/index.html#/does-not-exist"]


def test_the_file_url_guard_can_be_waived_deliberately(monkeypatch):
    monkeypatch.setenv("INSPECTOR_ALLOW_ELECTRON_NAVIGATE", "1")
    a = _adapter(_NavCDPStub(url="file:///Users/x/app/dist/index.html"))
    assert a.navigate("/does-not-exist") is True
    assert a.cdp.navigated == ["file:///does-not-exist"]


def test_navigate_refuses_a_relative_path_with_nothing_to_resolve_it_against():
    a = _adapter(_NavCDPStub(url=""))
    assert a.navigate("/does-not-exist") is False
    assert a.cdp.navigated == []


def test_set_viewport_moves_the_click_coordinate_space_with_it():
    """The load-bearing bit: `_viewport` is what bbox ratios are multiplied by, so a
    resize that forgets to update it lands every later click at the OLD scale."""
    a = _adapter(_NavCDPStub())
    a.cdp.eval_value = json.dumps(
        [{"label": "Save", "role": "button", "x": 100, "y": 200, "w": 80, "h": 40}])
    wide = a.detect_elements(b"PNG")[0]
    assert wide.center_px(*a.screen_size()) == (140, 220)

    assert a.set_viewport(375, 667, mobile=True) is True
    assert a.screen_size() == (375, 667)
    assert a.cdp.viewports == [(375, 667, True)]

    # the same button re-measured by the reflowed layout: full-bleed on a phone
    a.cdp.eval_value = json.dumps(
        [{"label": "Save", "role": "button", "x": 20, "y": 100, "w": 335, "h": 44}])
    narrow = a.detect_elements(b"PNG")[0]
    cx, cy = narrow.center_px(*a.screen_size())
    assert cx == 187 and abs(cy - 122) <= 1        # centred on the 375px screen
    # and what the stale 1280-wide space would have produced: off the right edge
    assert narrow.center_px(1280, 800)[0] > a.screen_size()[0]


def test_screenshot_downscales_to_the_new_viewport_after_a_resize():
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (750, 1334), "white").save(buf, "PNG")
    cdp = _NavCDPStub()
    cdp.screenshot = lambda: buf.getvalue()
    a = _adapter(cdp)
    assert a.set_viewport(375, 667)
    assert Image.open(io.BytesIO(a.screenshot())).size == (375, 667)


def test_a_failed_resize_leaves_the_old_coordinate_space_intact():
    a = _adapter(_NavCDPStub(ok=False))
    assert a.set_viewport(375, 667) is False
    assert a.screen_size() == (1280, 800)       # still the truth about the screen
    a.cdp.viewports.clear()
    assert a.set_viewport(0, 667) is False      # nonsense never reaches the browser
    assert a.cdp.viewports == [] and a.screen_size() == (1280, 800)


def test_clear_viewport_re_reads_the_real_size():
    a = _adapter(_NavCDPStub())
    assert a.set_viewport(375, 667)
    a.cdp.eval_value = json.dumps([1280, 800])
    assert a.clear_viewport() is True
    assert a.cdp.cleared == 1 and a.screen_size() == (1280, 800)


# --- session state (without it every run starts logged out and re-drives the login UI) ---

class _StateCDP(CDPClient):
    """CDPClient with the socket swapped for a toy browser: a cookie jar and a real pair
    of stores. The REAL CookieParam projection and the REAL storage expressions run
    against it, so the round trip is exercised rather than asserted about."""

    def __init__(self, url="http://localhost:3000/app", local=None, session=None,
                 storage_error=""):
        self.url = url
        self.local = dict(local or {})
        self.session = dict(session or {})
        self.jar: list[dict] = []
        self.sent: list[tuple[str, dict]] = []
        self.storage_error = storage_error

    def current_url(self): return self.url

    def _cmd(self, method, params=None):
        self.sent.append((method, params or {}))
        return {"cookies": [dict(c) for c in self.jar]} if method == "Network.getCookies" else {}

    def _cmd_ok(self, method, params=None):
        self.sent.append((method, params or {}))
        if method == "Network.setCookies":
            for c in (params or {}).get("cookies", []):
                if {"size", "session"} & set(c):     # CookieParam has no such fields
                    return False                     # → CDP rejects the whole batch
                self.jar.append(dict(c))
        return True

    def evaluate(self, expr, await_promise=False):
        from inspector.adapters.cdp_client import STORAGE_READ_JS
        if expr == STORAGE_READ_JS:
            return json.dumps({"local": self.local, "session": self.session})
        if self.storage_error:
            return self.storage_error
        local, session = _write_args(expr)
        self.local.update(local)
        self.session.update(session)
        return ""


def _write_args(expr):
    """Pull the two JSON object literals back out of a storage-write expression."""
    from inspector.adapters.cdp_client import STORAGE_WRITE_FN
    args = expr[len(STORAGE_WRITE_FN) + 1:-1]
    dec = json.JSONDecoder()
    local, end = dec.raw_decode(args)
    session, _ = dec.raw_decode(args[end + 1:])
    return local, session


def test_set_cookies_projects_a_captured_cookie_onto_what_cdp_accepts():
    # getCookies hands back `Cookie`, setCookies wants `CookieParam`: `size`/`session` are
    # output-only and make the browser reject the WHOLE batch, and expires=-1 (how a
    # session cookie is reported) reads back as an expiry in 1969.
    cdp = _StateCDP()
    captured = {"name": "sid", "value": "abc123", "domain": "localhost", "path": "/",
                "httpOnly": True, "secure": False, "sameSite": "Lax",
                "expires": -1, "size": 9, "session": True}
    assert CDPClient.set_cookies(cdp, [captured]) is True
    placed = cdp.jar[0]
    assert placed == {"name": "sid", "value": "abc123", "domain": "localhost", "path": "/",
                      "httpOnly": True, "secure": False, "sameSite": "Lax"}
    assert "expires" not in placed and "size" not in placed and "session" not in placed


def test_set_cookies_keeps_a_real_expiry_and_refuses_unplaceable_records():
    cdp = _StateCDP()
    assert CDPClient.set_cookies(cdp, [{"name": "sid", "value": "v", "url": "http://a/",
                                        "expires": 1893456000}]) is True
    assert cdp.jar[0]["expires"] == 1893456000
    fresh = _StateCDP()
    assert CDPClient.set_cookies(fresh, []) is False
    assert CDPClient.set_cookies(fresh, [{"value": "v", "domain": "a"}]) is False  # no name
    assert CDPClient.set_cookies(fresh, [{"name": "sid", "value": "v"}]) is False  # no origin
    assert fresh.sent == []                     # nothing usable → nothing sent


def test_get_cookies_returns_the_browsers_view_including_httponly():
    cdp = _StateCDP()
    cdp.jar = [{"name": "sid", "value": "abc", "domain": "localhost", "httpOnly": True}]
    got = CDPClient.get_cookies(cdp)
    assert got[0]["httpOnly"] is True           # the one document.cookie cannot see
    assert CDPClient.get_cookies(_NavCDP()) == []          # dead socket → neutral empty


def test_storage_round_trips_through_the_page():
    cdp = _StateCDP()
    assert CDPClient.set_storage(cdp, "http://localhost:3000",
                                 local={"token": 'ey."J\\x', "n": 7},
                                 session={"step": "2"}) is True
    out = CDPClient.get_storage(cdp, "http://localhost:3000")
    assert out["local"] == {"token": 'ey."J\\x', "n": "7"}   # non-strings stored as JSON
    assert out["session"] == {"step": "2"}


def test_set_storage_refuses_to_write_into_the_wrong_origin():
    # Writing the seed into whatever page happens to be on screen is the silent failure
    # worth a guard: nothing errors, the app boots logged out anyway.
    cdp = _StateCDP(url="http://localhost:3001/other")
    assert CDPClient.set_storage(cdp, "http://localhost:3000", local={"token": "t"}) is False
    assert cdp.local == {}
    assert CDPClient.set_storage(cdp, "http://localhost:3000") is True   # nothing asked for


def test_set_storage_reports_an_origin_that_cannot_store():
    cdp = _StateCDP(storage_error="localStorage: SecurityError")
    assert CDPClient.set_storage(cdp, "", local={"token": "t"}) is False


def test_get_storage_refuses_to_hand_back_another_pages_state():
    cdp = _StateCDP(url="http://localhost:3001/other", local={"token": "t"})
    assert CDPClient.get_storage(cdp, "http://localhost:3000") == {}
    assert CDPClient.get_storage(cdp)["local"] == {"token": "t"}   # '' = wherever we are
    assert CDPClient.get_storage(_NavCDP()) == {}                  # dead socket → neutral


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_real_storage_expressions_round_trip_awkward_values(tmp_path):
    """Run the REAL write and read expressions under node against a Storage stub: a token
    with quotes, a backslash and a newline in it must come back byte-identical, since that
    is exactly what a JWT-ish value looks like and what naive string building destroys."""
    from inspector.adapters.cdp_client import STORAGE_READ_JS, _storage_write_js
    values = {"token": 'ab"c\\d\ne', "u": "{\"id\":1}", "emoji": "ok ✅"}
    stub = r"""
class Store {
  constructor(){ this.m = new Map(); }
  get length(){ return this.m.size; }
  key(i){ return [...this.m.keys()][i]; }
  getItem(k){ const v = this.m.get(k); return v === undefined ? null : v; }
  setItem(k, v){ this.m.set(String(k), String(v)); }
}
global.localStorage = new Store();
global.sessionStorage = new Store();
"""
    f = tmp_path / "storage_expr.cjs"
    f.write_text(stub + "const err = " + _storage_write_js(values, {"step": "2"}) + ";\n"
                 + "console.log(JSON.stringify({ err, read: JSON.parse(" + STORAGE_READ_JS
                 + ") }));\n")
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["err"] == ""
    assert out["read"]["local"] == values
    assert out["read"]["session"] == {"step": "2"}


class _StateCDPStub:
    """Adapter-facing fake browser — a cookie jar, two stores and a call log, so the
    ordering `seed_state` has to enforce is directly observable. `set_storage` asserts
    the precondition the real client enforces, so seeding before navigating BLOWS UP
    here rather than passing quietly the way it would in a real browser."""

    def __init__(self, url="about:blank", ok=True):
        self.url = url
        self.ok = ok
        self.jar: list[dict] = []
        self.local: dict = {}
        self.session: dict = {}
        self.calls: list[str] = []

    def current_url(self): return self.url
    def evaluate(self, expr, await_promise=False): return json.dumps([1280, 800])

    def get_cookies(self, urls=None):
        self.calls.append("get_cookies")
        return [dict(c) for c in self.jar]

    def get_storage(self, origin=""):
        self.calls.append("get_storage")
        return {"local": dict(self.local), "session": dict(self.session)}

    def set_cookies(self, cookies):
        self.calls.append("set_cookies")
        if not self.ok:
            return False
        self.jar = [dict(c) for c in cookies]
        return True

    def set_storage(self, origin, local=None, session=None):
        self.calls.append("set_storage")
        assert origin_of(origin) == origin_of(self.url), "seeded storage before navigating"
        if not self.ok:
            return False
        self.local.update(local or {})
        self.session.update(session or {})
        return True

    def navigate(self, url):
        self.calls.append("navigate")
        if not self.ok:
            return False
        self.url = url
        return True

    def reload(self):
        self.calls.append("reload")
        return self.ok


def _state():
    return {"origin": "http://localhost:3000",
            "cookies": [{"name": "sid", "value": "abc", "domain": "localhost"}],
            "local_storage": {"token": "ey.J"}, "session_storage": {"step": "2"}}


def test_seed_state_sets_cookies_navigates_seeds_storage_then_reloads():
    # The ordering IS the feature: storage written before the navigation lands in
    # about:blank's store and is silently thrown away, and without the trailing reload the
    # app is still showing the render it did with an empty store.
    a = _adapter(_StateCDPStub(url="about:blank"))
    assert a.seed_state(_state()) is True
    assert a.cdp.calls == ["set_cookies", "navigate", "set_storage", "reload"]
    assert a.cdp.url == "http://localhost:3000"
    assert a.cdp.local == {"token": "ey.J"} and a.cdp.session == {"step": "2"}
    assert a.cdp.jar[0]["name"] == "sid"


def test_seed_state_skips_the_navigation_when_already_on_the_origin():
    a = _adapter(_StateCDPStub(url="http://localhost:3000/items"))
    assert a.seed_state({"origin": "http://localhost:3000",
                         "local_storage": {"token": "t"}}) is True
    assert a.cdp.calls == ["set_storage", "reload"]
    assert a.cdp.url == "http://localhost:3000/items"      # stays where the caller was


def test_seed_state_stops_when_it_cannot_reach_the_origin():
    a = _adapter(_StateCDPStub(url="about:blank", ok=False))
    assert a.seed_state(_state()) is False
    assert "set_storage" not in a.cdp.calls      # never seed into the wrong origin
    assert a.cdp.local == {}


def test_capture_state_round_trips_through_seed_state():
    src = _StateCDPStub(url="http://localhost:3000/dashboard")
    src.jar = [{"name": "sid", "value": "abc", "domain": "localhost", "path": "/",
                "httpOnly": True}]
    src.local = {"token": "ey.J", "theme": "dark"}
    src.session = {"step": "2"}
    state = _adapter(src).capture_state()
    assert state["origin"] == "http://localhost:3000"
    assert json.loads(json.dumps(state)) == state        # survives a trip through a file

    fresh = _adapter(_StateCDPStub(url="about:blank"))
    assert fresh.seed_state(state) is True
    assert fresh.capture_state() == state                # the session came back intact


def test_seed_state_reports_unsupported_instead_of_claiming_success():
    from inspector.adapters.base import SurfaceAdapter
    a = _adapter(_StateCDPStub())
    a.cdp = None
    assert a.seed_state(_state()) is False and a.capture_state() == {}
    # a surface with no session capability at all answers the same way, and must never
    # answer True: a caller told "seeded" reads every logged-out screen as an app bug.
    assert SurfaceAdapter.seed_state(a, _state()) is False
    assert SurfaceAdapter.capture_state(a) == {}


def test_seed_state_refuses_a_state_that_would_install_nothing():
    a = _adapter(_StateCDPStub())
    assert a.seed_state({}) is False
    assert a.seed_state({"origin": "http://localhost:3000"}) is False
    assert a.seed_state("not a dict") is False
    assert a.cdp.calls == []


def test_get_adapter_local_vs_vm_electron():
    from inspector.adapters.electron import ElectronAdapter
    assert isinstance(get_adapter(Surface.ELECTRON, Config(execution="local")), LocalElectronAdapter)
    # The sandboxed branch needs a key now: without one get_adapter refuses up front
    # rather than failing deep inside the e2b client.
    vm = Config(execution="vm", e2b_api_key="e2b_test")
    assert isinstance(get_adapter(Surface.ELECTRON, vm), ElectronAdapter)
