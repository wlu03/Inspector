"""Synchronous Chrome DevTools Protocol client for LOCAL Chromium surfaces.

Drives a local Electron/Chrome renderer over a WebSocket — screenshot, input,
console capture, network capture, and DOM eval — all through one channel, no OS-level
tools (xdotool/cliclick/screencapture). Shared by local Electron and (later) local web.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.parse

from ..models import Element

# CDP Input.dispatchKeyEvent wants DOM key names.
_KEY_MAP = {
    "enter": "Enter", "return": "Enter", "tab": "Tab", "escape": "Escape",
    "backspace": "Backspace", "delete": "Delete", "space": " ",
    "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
}

# Returns a JSON string of visible interactive elements with CSS-pixel rects.
DOM_ELEMENTS_JS = r"""JSON.stringify(
  [...document.querySelectorAll('button,a,input,select,textarea,[role=button],[role=link],[role=tab],[role=checkbox],[role=switch],[onclick],[tabindex]')]
    .filter(el => { const s = getComputedStyle(el);
      return s.display!=='none' && s.visibility!=='hidden' && el.offsetParent!==null; })
    .map(el => { const r = el.getBoundingClientRect();
      return { label: (el.innerText||el.value||el.getAttribute('aria-label')||
                       el.getAttribute('placeholder')||el.getAttribute('title')||'').trim().slice(0,80),
               role: (el.getAttribute('role')||el.tagName||'').toLowerCase(),
               x: r.x, y: r.y, w: r.width, h: r.height }; })
    .filter(e => e.w>1 && e.h>1)
)"""


# Leaf-ish static text (the displayed values/labels the interactive selector misses —
# a counter's <div>0</div>, a "Notifications" caption). Needed so oracles can READ state.
DOM_TEXT_JS = r"""JSON.stringify(
  [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,p,label,output,li,span,div,strong,b,td,th,[role=status]')]
    .filter(el => { const s = getComputedStyle(el);
      if (s.display==='none'||s.visibility==='hidden'||el.offsetParent===null) return false;
      if (el.querySelector('button,a,input,select,textarea,h1,h2,h3,h4,h5,h6,p,li,div,span,output')) return false;
      const t = (el.innerText||'').trim();
      return t.length>0 && t.length<=40 && !t.includes('\n'); })
    .map(el => { const r = el.getBoundingClientRect();
      return { label:(el.innerText||'').trim().slice(0,80),
               role:(el.getAttribute('role')||el.tagName||'').toLowerCase(),
               x:r.x, y:r.y, w:r.width, h:r.height }; })
    .filter(e => e.w>1 && e.h>1)
)"""


# The DETERMINISTIC audit, as ONE in-page async IIFE returning a JSON string. This is
# the single definition of the audit: the sandboxed path (adapters/cdp.py) embeds it in
# the Node runner it writes into the VM, the local path evaluates it straight over the
# CDP socket. Keeping one copy is the point — two copies drift, and a drifted audit
# reports different facts on the two execution planes.
#
# It reads three structured signals off the live DOM: WCAG violations (axe-core),
# images that failed to load (naturalWidth=0), and inputs with no accessible label.
# Only the first needs axe; the other two are pure DOM and MUST keep working when axe
# is unavailable, so each check sits in its own try/catch. `axe_ran` is the honest
# receipt that the a11y pass actually happened — without it an empty `axe_violations`
# is indistinguishable from a pass, which is exactly the failure this audit exists to
# prevent. Callers evaluate it with awaitPromise so axe finishes before the read.
DOM_AUDIT_EXPR = r"""(async () => {
  const out = { axe_violations: [], broken_images: [], unlabeled_inputs: [] };
  try {
    out.broken_images = [...document.images]
      .filter(i => i.complete && i.naturalWidth === 0)
      .map(i => i.currentSrc || i.src || '(no src)').slice(0, 50);
  } catch (e) {}
  try {
    const forId = new Set();
    document.querySelectorAll('label[for]').forEach(l => forId.add(l.getAttribute('for')));
    out.unlabeled_inputs = [...document.querySelectorAll('input,select,textarea')]
      .filter(el => {
        if (el.type === 'hidden') return false;
        const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title');
        const ph = el.getAttribute('placeholder');
        const wrapped = el.closest('label');
        const labelled = el.id && forId.has(el.id);
        return !(aria || ph || wrapped || labelled);
      })
      .map(el => el.name || el.id || el.type || 'input').slice(0, 50);
  } catch (e) {}
  try {
    if (!window.axe) {
      await new Promise((res, rej) => {
        const s = document.createElement('script');
        s.src = 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js';
        s.onload = res;
        s.onerror = () => rej(new Error('axe-core CDN blocked (script-src CSP or no network)'));
        document.head.appendChild(s);
        setTimeout(() => rej(new Error('axe-core CDN load timed out')), 6000);
      });
    }
    if (window.axe) {
      const r = await window.axe.run(document, { resultTypes: ['violations'] });
      out.axe_violations = r.violations.map(v => ({
        id: v.id, impact: v.impact, help: v.help, nodes: (v.nodes || []).length }));
      out.axe_ran = true;
    } else {
      out.axe_error = 'axe-core loaded but never defined window.axe';
    }
  } catch (e) { out.axe_error = String((e && e.message) || e); }
  return JSON.stringify(out);
})()"""

# axe-core 4.10.2, vendored (see vendor/axe.min.js). Injecting the SOURCE TEXT over CDP
# is immune to the app's Content-Security-Policy, whereas appending a <script src> to a
# CDN is silently killed by any strict script-src — and a silently missing axe returns
# zero violations, which reads as a clean pass. The CDN stays as the fallback for when
# the vendored copy isn't on disk (e.g. a trimmed install).
_AXE_PATH = os.path.join(os.path.dirname(__file__), "vendor", "axe.min.js")
_axe_source_cache: str | None = None


def axe_source() -> str:
    """Return the vendored axe-core source text, or '' if it isn't bundled.

    Read once and cached — the file is ~550 KB and the audit may run many times per
    session. Never raises: a missing/unreadable vendor file just means the in-page CDN
    fallback (and the explicit `axe_error` it reports) takes over.
    """
    global _axe_source_cache
    if _axe_source_cache is None:
        try:
            with open(_AXE_PATH, encoding="utf-8") as fh:
                _axe_source_cache = fh.read()
        except Exception:
            _axe_source_cache = ""
    return _axe_source_cache


def parse_text_elements(raw, vw: int, vh: int, id_offset: int = 0) -> list[Element]:
    """Parse DOM_TEXT_JS into non-interactive Element[] (source='dom-text')."""
    els = parse_dom_elements(raw, vw, vh)
    out = []
    for e in els:
        e.id += id_offset
        e.interactivity = False
        e.source = "dom-text"
        out.append(e)
    return out


def control_state_js(index: int) -> str:
    """JS reading the i-th interactive element's structured state — SAME selector +
    filters as DOM_ELEMENTS_JS, so the index matches the Element id parse assigns."""
    return (r"""(function(i){
      const els = [...document.querySelectorAll('button,a,input,select,textarea,[role=button],[role=link],[role=tab],[role=checkbox],[role=switch],[onclick],[tabindex]')]
        .filter(el => { const s = getComputedStyle(el);
          return s.display!=='none' && s.visibility!=='hidden' && el.offsetParent!==null; })
        .filter(el => { const r = el.getBoundingClientRect(); return r.width>1 && r.height>1; });
      const el = els[i]; if(!el) return JSON.stringify({});
      return JSON.stringify({
        role: (el.getAttribute('role')||el.tagName||'').toLowerCase(),
        text: (el.innerText||el.value||'').trim().slice(0,80),
        value: ('value' in el) ? el.value : null,
        checked: (el.type==='checkbox'||el.type==='radio') ? !!el.checked : null,
        pressed: el.getAttribute('aria-pressed'),
        ariaChecked: el.getAttribute('aria-checked'),
        selected: el.getAttribute('aria-selected'),
        expanded: el.getAttribute('aria-expanded'),
      });
    })(INDEX)""").replace("INDEX", str(int(index)))


def parse_dom_elements(raw, vw: int, vh: int) -> list[Element]:
    """Parse the DOM_ELEMENTS_JS result into Element[] (bbox as 0..1 of the viewport). Pure.

    Like the iOS a11y tree, this is a native element source — exact CSS-pixel rects
    normalized by the viewport, so SoM/loop/driver are unchanged. source='dom'.
    """
    if not vw or not vh:
        return []
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    out: list[Element] = []
    for i, e in enumerate(items):
        if not isinstance(e, dict):
            continue
        try:
            x, y, w, h = float(e["x"]), float(e["y"]), float(e["w"]), float(e["h"])
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        out.append(Element(
            id=i, label=str(e.get("label", "")), role=str(e.get("role", "")),
            bbox=[x / vw, y / vh, (x + w) / vw, (y + h) / vh],
            interactivity=True, source="dom",
        ))
    return out


# Reads BOTH web storages back as a JSON string. The stores are read through the same
# API the app itself uses, so what a capture records is exactly what the app would have
# found there — and each store is caught separately, because an origin can have one of
# them blocked (a sandboxed document, third-party storage partitioning) while the other
# answers normally, and a captured half is worth more than a captured nothing.
STORAGE_READ_JS = r"""(function(){
  const out = { local: {}, session: {} };
  try { for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i); out.local[k] = localStorage.getItem(k); } } catch (e) {}
  try { for (let i = 0; i < sessionStorage.length; i++) {
    const k = sessionStorage.key(i); out.session[k] = sessionStorage.getItem(k); } } catch (e) {}
  return JSON.stringify(out);
})()"""

# The write half, as a function literal that `_storage_write_js` applies to two JSON
# object literals. It returns '' or the reason it could not write, rather than throwing:
# a seed that lands in an origin whose storage is blocked must be REPORTED, since the
# only other symptom is an app that quietly renders logged out.
STORAGE_WRITE_FN = r"""(function(l, s){
  try { for (const k in l) localStorage.setItem(k, l[k]); }
  catch (e) { return 'localStorage: ' + ((e && e.message) || e); }
  try { for (const k in s) sessionStorage.setItem(k, s[k]); }
  catch (e) { return 'sessionStorage: ' + ((e && e.message) || e); }
  return '';
})"""


def _storage_write_js(local: dict, session: dict) -> str:
    """Apply STORAGE_WRITE_FN to these two stores, embedding them as JSON literals.

    JSON is a subset of JS object-literal syntax, so `json.dumps` is also a correct
    JS-literal serializer — and it is the only safe way to get a session token into the
    expression. Tokens routinely contain quotes, backslashes and (base64url) characters
    that would end the string early if the expression were concatenated by hand, which
    corrupts the very value the app is about to read back.
    """
    return f"{STORAGE_WRITE_FN}({json.dumps(local)},{json.dumps(session)})"


def _storage_values(items) -> dict:
    """Normalise one store to the {str: str} shape the DOM actually holds.

    `setItem` stringifies whatever it is handed, and for a dict that means the literal
    '[object Object]' — a silently destroyed value. Anything that isn't already a string
    is therefore serialised as JSON here, which is what an app that stored structured
    state would have written in the first place.
    """
    if not isinstance(items, dict):
        return {}
    return {str(k): (v if isinstance(v, str) else json.dumps(v)) for k, v in items.items()}


# Cookies come OUT of Network.getCookies as `Cookie` and go back IN as `CookieParam`, and
# the shapes are not the same: `size` and `session` exist only on the way out, and CDP
# rejects the whole setCookies batch when it sees a field it does not know. Replaying a
# captured session therefore has to project every record onto the keys the browser will
# accept, or the seed fails wholesale and the run silently starts logged out.
_COOKIE_PARAM_KEYS = ("name", "value", "url", "domain", "path", "secure", "httpOnly",
                      "sameSite", "expires", "priority", "sameParty", "sourceScheme",
                      "sourcePort", "partitionKey")


def _cookie_param(cookie) -> dict | None:
    """Project one captured cookie onto CookieParam, or None if it is unusable."""
    if not isinstance(cookie, dict) or not cookie.get("name"):
        return None
    out = {k: cookie[k] for k in _COOKIE_PARAM_KEYS if cookie.get(k) is not None}
    out["name"] = str(out["name"])
    out["value"] = str(out.get("value", ""))
    # A session cookie is REPORTED with expires = -1, but that is not a timestamp the
    # browser will take back — it reads as an expiry in 1969 and the cookie is dropped on
    # arrival. Omitting the key is what "expires when the browser closes" means on the way
    # in, and session cookies are exactly the ones an auth flow tends to use.
    exp = out.get("expires")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp <= 0:
        out.pop("expires", None)
    if not out.get("url") and not out.get("domain"):
        return None  # the browser has no way to decide which origin it belongs to
    return out


def origin_of(url: str) -> str:
    """scheme://host[:port] for `url`, lowercased, or '' when it has no shareable origin.

    This is the identity that decides whether state we are about to write will be visible
    to the app: http://localhost:3000/items and http://localhost:3000/login share a
    localStorage, http://localhost:3001 does not. A document with no scheme+host
    (about:blank, a file:// bundle, '') has no origin others can share, and gets '' —
    callers treat that as "unknown", never as "matches".
    """
    try:
        parts = urllib.parse.urlsplit(url or "")
    except Exception:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


# A chatty SPA can issue thousands of requests between two drains (polling, analytics,
# lazy-loaded chunks). The buffer is capped so a long session can't grow without bound;
# when it overflows we drop SUCCESSFUL traffic first, because a completed 2xx is the one
# record a tester never needs, while a 500 or a dead fetch is the whole reason this
# channel exists. See `_is_network_noise`.
NETWORK_BUFFER_LIMIT = 200


def _is_network_noise(rec: dict) -> bool:
    """True for a request that finished successfully — the first thing to evict.

    Deliberately narrow: a record is only noise once we have SEEN a 2xx for it. Anything
    still in flight (status None) keeps its slot, because a request that never comes back
    is itself a finding, and because evicting it would orphan the response events that
    are still to arrive for that requestId.
    """
    status = rec.get("status")
    return not rec.get("failed") and isinstance(status, int) and 200 <= status < 300


def _stamp_duration(rec: dict, ts) -> None:
    """Record wall time from requestWillBeSent to this event, in ms.

    CDP timestamps are monotonic seconds, and both endpoints come off the same clock, so
    the subtraction is meaningful even though the values themselves are arbitrary. A
    missing start (we joined mid-request) simply leaves `duration_ms` as None rather than
    inventing a number.
    """
    start = rec.get("_start")
    if isinstance(start, (int, float)) and isinstance(ts, (int, float)):
        rec["duration_ms"] = max(0, int(round((ts - start) * 1000)))


class CDPClient:
    """One synchronous CDP session over a WebSocket (lazy `websocket-client`)."""

    def __init__(self, ws_url: str, timeout: int = 15):
        import websocket  # lazy import (websocket-client is a base dep)

        # suppress_origin: modern Chromium 403-rejects CDP WS connections whose Origin
        # header isn't allow-listed; sending no Origin avoids that (belt with the
        # launcher's --remote-allow-origins=* suspenders).
        self._ws = websocket.create_connection(
            ws_url, timeout=timeout, max_size=None, suppress_origin=True,
        )
        self._id = 0
        self._console: list[str] = []
        # requestId -> one merged record. A dict (insertion-ordered) rather than a list
        # because four separate CDP events describe a single request and they must all
        # land on the same row; insertion order doubles as the eviction order.
        self._network: dict[str, dict] = {}
        # Monotonic count of Page.loadEventFired. Navigation waits on it INCREASING from
        # a baseline taken before the command, which is race-proof: if the load fires
        # while `_cmd` is still reading toward its own reply, the event is counted there
        # and the wait returns instantly instead of blocking for a load already past.
        self._load_count = 0
        self._timeout = timeout

    def _cmd(self, method: str, params: dict | None = None) -> dict:
        return self._cmd_raw(method, params).get("result", {})

    def _cmd_raw(self, method: str, params: dict | None = None) -> dict:
        """Send one command and return the WHOLE reply envelope, {} if the socket is dead.

        `_cmd` throws the envelope away and keeps `result`, which is fine for commands
        that answer with data. It is not fine for the navigation/emulation commands,
        whose successful `result` is itself `{}` — indistinguishable from the `{}` that
        means "the socket is gone". Those callers have to return an honest can't-do-that
        signal, so they read `error`/`result` off the envelope instead.
        """
        self._id += 1
        mid = self._id
        try:
            self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        except Exception:
            return {}
        while True:
            try:
                msg = json.loads(self._ws.recv())
            except Exception:
                return {}
            if msg.get("id") == mid:
                return msg
            self._on_event(msg)  # buffer console/log/exception events seen meanwhile

    def _cmd_ok(self, method: str, params: dict | None = None) -> bool:
        """True only when the browser actually acknowledged the command."""
        env = self._cmd_raw(method, params)
        return bool(env) and "error" not in env

    def _on_event(self, msg: dict) -> None:
        m = msg.get("method")
        p = msg.get("params") or {}
        if m == "Runtime.consoleAPICalled":
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            self._console.append(f"[console.{p.get('type')}] {args}")
        elif m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            desc = (d.get("exception") or {}).get("description") or d.get("text", "")
            self._console.append(f"[exception] {desc}")
        elif m == "Log.entryAdded":
            e = p.get("entry", {})
            self._console.append(f"[log.{e.get('level')}] {e.get('text')}")
        elif m == "Network.requestWillBeSent":
            rec = self._network_record(p.get("requestId"))
            req = p.get("request") or {}
            rec["method"] = str(req.get("method") or "")
            rec["url"] = str(req.get("url") or "")
            rec["resource_type"] = str(p.get("type") or "")
            rec["_start"] = p.get("timestamp")
        elif m == "Network.responseReceived":
            rec = self._network_record(p.get("requestId"))
            resp = p.get("response") or {}
            status = resp.get("status")
            if isinstance(status, (int, float)) and not isinstance(status, bool):
                rec["status"] = int(status)
            rec["mime_type"] = str(resp.get("mimeType") or "")
            if not rec["url"]:
                rec["url"] = str(resp.get("url") or "")
            _stamp_duration(rec, p.get("timestamp"))
        elif m == "Network.loadingFailed":
            rec = self._network_record(p.get("requestId"))
            rec["failed"] = True
            rec["error"] = str(
                p.get("errorText") or p.get("blockedReason")
                or ("canceled" if p.get("canceled") else "request failed")
            )
            _stamp_duration(rec, p.get("timestamp"))
        elif m == "Page.loadEventFired":
            self._load_count += 1
        elif m == "Network.loadingFinished":
            _stamp_duration(self._network_record(p.get("requestId")), p.get("timestamp"))

    def _network_record(self, request_id) -> dict:
        """Get-or-create the single record this requestId correlates into.

        Creating on a LATE event (a response whose requestWillBeSent was already drained,
        or that was in flight when Network.enable ran) is deliberate: a 500 or a dead
        fetch must never be dropped just because we missed the start of its request. Such
        a record is simply born with empty method/url and fills in from what does arrive.
        """
        key = str(request_id or "")
        rec = self._network.get(key)
        if rec is None:
            rec = {"request_id": key, "method": "", "url": "", "resource_type": "",
                   "status": None, "mime_type": "", "failed": False, "error": "",
                   "duration_ms": None}
            self._network[key] = rec
            while len(self._network) > NETWORK_BUFFER_LIMIT:
                victim = next((k for k, r in self._network.items() if _is_network_noise(r)),
                              next(iter(self._network)))
                del self._network[victim]
        return rec

    def enable(self) -> None:
        self._cmd("Runtime.enable")
        self._cmd("Log.enable")
        self._cmd("Page.enable")
        # Network is what makes backend bugs visible at all — a 500, a CORS rejection or
        # a fetch that never resolves produces no console line and no visual change, so
        # without this domain the tool reports a clean run on a broken API.
        self._cmd("Network.enable")

    def drain_console(self) -> list[str]:
        self._pump()
        out, self._console = self._console, []
        return out

    def drain_network(self) -> list[dict]:
        """Return the requests seen since the previous call, then forget them.

        Same drain-and-clear contract as `drain_console` so the two channels can be read
        the same way around an action — but kept strictly SEPARATE from it: network events
        are never rendered into console lines, or every failed fetch would be counted
        twice by anything that scans logs for errors.

        Each record is {request_id, method, url, resource_type, status, mime_type, failed,
        error, duration_ms}. A request still in flight at drain time is returned with
        whatever is known (status None); its later events land on a fresh record with the
        same request_id in the NEXT drain, which is the honest reading — the caller asked
        what happened during that window.
        """
        self._pump()
        records, self._network = self._network, {}
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in records.values()]

    def _pump(self, budget: float = 0.1) -> None:
        """Read any buffered events without blocking the loop."""
        try:
            self._ws.settimeout(budget)
            while True:
                try:
                    msg = json.loads(self._ws.recv())
                except Exception:
                    break
                self._on_event(msg)
        finally:
            try:
                self._ws.settimeout(self._timeout)
            except Exception:
                pass

    def screenshot(self) -> bytes:
        r = self._cmd("Page.captureScreenshot", {"format": "png"})
        data = r.get("data")
        try:
            return base64.b64decode(data) if data else b""
        except Exception:
            return b""

    def click(self, x: int, y: int, clicks: int = 1) -> None:
        # clickCount increments per press so the DOM sees detail=2 on the 2nd press —
        # required for `dblclick` handlers to fire (two clickCount:1 clicks won't).
        for n in range(1, clicks + 1):
            self._cmd("Input.dispatchMouseEvent",
                      {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": n})
            self._cmd("Input.dispatchMouseEvent",
                      {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": n})

    def type_text(self, text: str) -> None:
        self._cmd("Input.insertText", {"text": text or ""})

    def key(self, key_name: str) -> None:
        k = _KEY_MAP.get((key_name or "").lower(), key_name)
        self._cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": k})
        self._cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": k})

    def scroll(self, x: int, y: int, dy: int) -> None:
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy})

    def hover(self, x: int, y: int) -> None:
        """Move the pointer over (x, y) without pressing anything.

        A real mouseMoved is the only way to reach hover-only UI — a dropdown that opens
        on hover, a tooltip, a row's delete button that only appears on mouseover. A
        synthesized DOM event would not update `:hover` at all, so the CSS half of that
        UI (most of it) would never render and the check would be meaningless.
        """
        self._cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    def right_click(self, x: int, y: int) -> None:
        """Press and release the right button, which is what makes Chromium raise the
        page's `contextmenu` event — the entry point to every custom context menu, and
        the one input the left-button `click` path can never produce."""
        for phase in ("mousePressed", "mouseReleased"):
            self._cmd("Input.dispatchMouseEvent",
                      {"type": phase, "x": x, "y": y, "button": "right", "clickCount": 1})

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1})
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mouseMoved", "x": x2, "y": y2, "button": "left"})
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1})

    def _wait_for_load(self, baseline: int, timeout: float) -> bool:
        """Block until Page.loadEventFired pushes `_load_count` past `baseline`.

        This is what replaces the blind `time.sleep` a naive navigate would use: a sleep
        either wastes seconds on a fast route or reads the DOM of the PREVIOUS page on a
        slow one, and the second failure mode silently invents findings ("the button
        disappeared") that are really just a screenshot taken too early. Events that
        arrive meanwhile still go through `_on_event`, so console lines and requests
        emitted during the load are kept rather than thrown away.

        Returns False on a dead socket or when the budget runs out — the caller decides
        what that means, because a page still loading has nonetheless navigated.
        """
        deadline = time.monotonic() + timeout
        try:
            while self._load_count == baseline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                try:
                    self._ws.settimeout(remaining)
                    msg = json.loads(self._ws.recv())
                except Exception:
                    return False  # socket timed out or died mid-load
                self._on_event(msg)
        finally:
            try:
                self._ws.settimeout(self._timeout)
            except Exception:
                pass
        return True

    def navigate(self, url: str, timeout: float = 15.0) -> bool:
        """Point the page at `url` and wait for its load event. True if it went there.

        The return value is deliberately a hard signal rather than None: a caller that
        cannot tell a navigation apart from a no-op will happily report "the /does-not-
        exist route renders fine" about a page that never left the home screen.

        `errorText` on the reply means the browser REFUSED to go (bad scheme, host that
        will not resolve) and is a False. A 404 from a server that did answer is not —
        that navigation succeeded, and its status shows up on the network channel, which
        is exactly the evidence a bogus-route probe is after. A load event that never
        arrives inside the budget is also not a False: the page is somewhere new and
        slow, and the caller should go look at it.
        """
        if not url:
            return False
        baseline = self._load_count
        env = self._cmd_raw("Page.navigate", {"url": url})
        result = env.get("result")
        if not isinstance(result, dict) or result.get("errorText"):
            return False
        self._wait_for_load(baseline, timeout)
        return True

    def back(self) -> bool:
        """Step one entry back in session history; False if there is nowhere to go."""
        return self._history_step(-1)

    def forward(self) -> bool:
        """Step one entry forward in session history; False if there is nowhere to go."""
        return self._history_step(1)

    def _history_step(self, delta: int, timeout: float = 15.0) -> bool:
        """Walk the navigation history by `delta` entries.

        There is no Page.goBack in CDP — history is read as a list plus a cursor and
        then re-entered by entry id. Doing it this way has a real benefit over a
        synthesized `history.back()`: running off the end of the history is VISIBLE here
        (the index simply has no neighbour), so we report it instead of dispatching a
        no-op the caller would read as a successful back navigation.
        """
        hist = self._cmd("Page.getNavigationHistory")
        entries = hist.get("entries") if isinstance(hist, dict) else None
        index = hist.get("currentIndex") if isinstance(hist, dict) else None
        if not isinstance(entries, list) or not isinstance(index, int):
            return False
        target = index + delta
        if target < 0 or target >= len(entries):
            return False
        entry = entries[target] if isinstance(entries[target], dict) else {}
        entry_id = entry.get("id")
        if entry_id is None:
            return False
        baseline = self._load_count
        if not self._cmd_ok("Page.navigateToHistoryEntry", {"entryId": entry_id}):
            return False
        # A restored entry can come back out of the back/forward cache without firing a
        # load event at all, so the wait is best-effort and its result is not the verdict.
        self._wait_for_load(baseline, timeout)
        return True

    def reload(self, timeout: float = 15.0) -> bool:
        """Reload the current document and wait for it to load again."""
        baseline = self._load_count
        if not self._cmd_ok("Page.reload", {}):
            return False
        self._wait_for_load(baseline, timeout)
        return True

    def current_url(self) -> str:
        """The URL of the document on screen, or '' when it cannot be read.

        Read off the navigation history rather than by evaluating `location.href`: the
        history is a browser-side fact that survives a page whose JS has thrown, a
        strict CSP, or a document still parsing. The eval is kept only as a fallback for
        a target that answers Runtime but not Page.
        """
        hist = self._cmd("Page.getNavigationHistory")
        entries = hist.get("entries") if isinstance(hist, dict) else None
        index = hist.get("currentIndex") if isinstance(hist, dict) else None
        if isinstance(entries, list) and isinstance(index, int) and 0 <= index < len(entries):
            entry = entries[index]
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
        try:
            return str(self.evaluate("location.href") or "")
        except Exception:
            return ""

    def set_viewport(self, width: int, height: int, mobile: bool = False) -> bool:
        """Resize the page to width x height CSS px (the responsive-layout probe).

        deviceScaleFactor is pinned to 1 on purpose. The whole local pipeline assumes
        screenshot pixels == CSS pixels == Input.* coordinates; a 2x capture would have
        to be downscaled by the adapter on every frame, and any drift between the two
        numbers lands every click somewhere other than where the agent looked.

        `mobile` additionally flips the mobile flag (viewport meta tag honoured, mobile
        UA layout) and touch emulation, because a "does it work at 375px" check that
        keeps hover-only affordances alive is testing a layout no phone will ever render.
        """
        w, h = int(width or 0), int(height or 0)
        if w <= 0 or h <= 0:
            return False
        ok = self._cmd_ok("Emulation.setDeviceMetricsOverride",
                          {"width": w, "height": h, "deviceScaleFactor": 1,
                           "mobile": bool(mobile)})
        if ok:
            self._cmd_ok("Emulation.setTouchEmulationEnabled",
                         {"enabled": bool(mobile), "maxTouchPoints": 1 if mobile else 0})
        return ok

    def clear_viewport_override(self) -> bool:
        """Hand the page back to the real window size.

        Callers that track a viewport of their own (the local adapters do — clicks are
        mapped through it) must re-read the size afterwards, since this restores a
        number this client does not know.
        """
        ok = self._cmd_ok("Emulation.clearDeviceMetricsOverride")
        self._cmd_ok("Emulation.setTouchEmulationEnabled", {"enabled": False,
                                                            "maxTouchPoints": 0})
        return ok

    def set_cookies(self, cookies) -> bool:
        """Install cookies into the browser, ideally BEFORE the app is loaded.

        Cookies are the usual carrier of a session, and unlike web storage they are keyed
        by domain rather than by the document on screen — so they can, and should, be set
        while the page is still on about:blank. The app's very first request then already
        carries the session and the login redirect never happens, which is the difference
        between a run that starts at the feature under test and one that spends its
        iteration budget clicking through a login form.

        False when nothing usable was in the batch (no name, or no url/domain to attach it
        to) or the browser refused it. Records are projected through `_cookie_param` first
        — see there for why a straight round trip of getCookies output does not work.
        """
        params = [p for p in (_cookie_param(c) for c in (cookies or [])) if p]
        if not params:
            return False
        return self._cmd_ok("Network.setCookies", {"cookies": params})

    def get_cookies(self, urls: list[str] | None = None) -> list[dict]:
        """Every cookie visible to the current page (or to `urls`), as CDP reports them.

        Read over CDP rather than out of `document.cookie` precisely because the session
        cookie an app cares about is usually httpOnly, which the page cannot see at all —
        a capture built from JS would look complete and replay as a logged-out session.
        Records are returned unmodified so the capture keeps secure/sameSite/expiry too.
        `[]` on a dead socket, like every other read here.
        """
        res = self._cmd("Network.getCookies", {"urls": urls} if urls else {})
        found = res.get("cookies") if isinstance(res, dict) else None
        return [c for c in found if isinstance(c, dict)] if isinstance(found, list) else []

    def set_storage(self, origin: str, local: dict | None = None,
                    session: dict | None = None) -> bool:
        """Write local/sessionStorage — into a page that is ALREADY ON `origin`.

        Both stores are partitioned by origin and the only handle on an origin's store is
        a document loaded from it, so this refuses when the page is somewhere else instead
        of writing into whatever happens to be on screen. That guard is worth its weight:
        seeding the wrong origin raises nothing, logs nothing and leaves the app booting
        logged out, and the agent then spends the run hunting a bug in a login flow that
        works fine. Callers should go through `SurfaceAdapter.seed_state`, which owns the
        navigate → seed → reload ordering this precondition implies.

        An empty seed is vacuously done (True). `origin=''` means "wherever we are", which
        is the only thing a document without a shareable origin can be told.
        """
        local, session = _storage_values(local), _storage_values(session)
        if not local and not session:
            return True
        here = origin_of(self.current_url())
        want = origin_of(origin)
        if want and want != here:
            logging.getLogger("inspector").warning(
                "storage seed refused: asked for %s but the page is on %s", want, here or "?")
            return False
        err = self.evaluate(_storage_write_js(local, session))
        if err:
            logging.getLogger("inspector").warning("storage seed failed: %s", err)
        return err == ""

    def get_storage(self, origin: str = "") -> dict:
        """Read both web storages back as {'local': {...}, 'session': {...}}.

        `origin` is a precondition, not a selector — there is no way to read another
        origin's store from this page — so a mismatch answers `{}` rather than quietly
        handing back the state of whatever is on screen, which would be written into a
        state file and replayed later as if it were the session that was captured. Pass
        '' (the default) for "whatever this page is", which is what a capture wants.
        `{}` too on a dead socket or an unparseable payload.
        """
        if origin and origin_of(origin) != origin_of(self.current_url()):
            return {}
        try:
            raw = self.evaluate(STORAGE_READ_JS)
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return {"local": data.get("local") or {}, "session": data.get("session") or {}}

    def evaluate(self, expr: str, await_promise: bool = False):
        r = self._cmd("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
        return (r.get("result") or {}).get("value")

    def inject_axe(self) -> str:
        """Define `window.axe` from the vendored source; return '' on success, else why.

        Evaluating the library's own text is the CSP-proof path — Runtime.evaluate is
        not subject to the page's script-src, so this works on apps where the CDN
        <script> tag the in-page fallback appends would be blocked. The return value is
        a REASON string rather than a bool because the caller has to be able to tell the
        agent why the a11y pass is missing instead of implying there was nothing to find.
        """
        src = axe_source()
        if not src:
            return "vendored axe-core is missing; falling back to the CDN"
        try:
            if self.evaluate("typeof window.axe") == "object":
                return ""  # already injected (a repeat audit on the same page)
            kind = self.evaluate(src + "\n;typeof window.axe")
        except Exception as exc:
            return f"axe-core injection failed: {exc}"
        if kind != "object":
            return f"axe-core injection did not define window.axe (typeof {kind!r})"
        return ""

    def audit_dom(self) -> dict:
        """Run the deterministic DOM audit in the live page and return its signals.

        Returns {axe_violations, broken_images, unlabeled_inputs} plus, whenever the
        a11y pass did NOT run, an `axe_error` explaining why. That key is the whole
        point: an empty `axe_violations` from a blocked axe-core is otherwise
        indistinguishable from a clean page, and the caller would report a pass it
        never earned. The pure-DOM checks are unaffected by an axe failure.

        Degrades to {} on a dead socket / unparseable payload, like every other
        perception call here — one broken subsystem must not end the run.
        """
        inject_error = self.inject_axe()
        try:
            raw = self.evaluate(DOM_AUDIT_EXPR, await_promise=True)
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        if not data.get("axe_ran"):
            reason = data.get("axe_error") or "axe-core did not run"
            data["axe_error"] = f"{reason} [{inject_error}]" if inject_error else reason
        return data

    def control_state(self, index: int) -> dict:
        try:
            raw = self.evaluate(control_state_js(index))
            return json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            return {}

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
