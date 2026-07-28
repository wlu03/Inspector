"""Synchronous Chrome DevTools Protocol client for LOCAL Chromium surfaces.

Drives a local Electron/Chrome renderer over a WebSocket — screenshot, input,
console capture, and DOM eval — all through one channel, no OS-level tools
(xdotool/cliclick/screencapture). Shared by local Electron and (later) local web.
"""

from __future__ import annotations

import base64
import json
import os

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
        self._timeout = timeout

    def _cmd(self, method: str, params: dict | None = None) -> dict:
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
                return msg.get("result", {})
            self._on_event(msg)  # buffer console/log/exception events seen meanwhile

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

    def enable(self) -> None:
        self._cmd("Runtime.enable")
        self._cmd("Log.enable")
        self._cmd("Page.enable")

    def drain_console(self) -> list[str]:
        self._pump()
        out, self._console = self._console, []
        return out

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

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1})
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mouseMoved", "x": x2, "y": y2, "button": "left"})
        self._cmd("Input.dispatchMouseEvent",
                  {"type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1})

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
