"""Synchronous Chrome DevTools Protocol client for LOCAL Chromium surfaces.

Drives a local Electron/Chrome renderer over a WebSocket — screenshot, input,
console capture, and DOM eval — all through one channel, no OS-level tools
(xdotool/cliclick/screencapture). Shared by local Electron and (later) local web.
"""

from __future__ import annotations

import base64
import json

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
        import websocket  # lazy — the `web` optional dep

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
