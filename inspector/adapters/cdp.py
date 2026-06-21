from __future__ import annotations

import json

# Fallback Node path (the web adapter installs Node here; Electron may have system node).
_NODE_FALLBACK = "/home/user/node/bin/node"

# One-shot: connect to CDP, enumerate the VISIBLE interactive elements actually in the
# live DOM, print their labels as a JSON list, exit. Shared by web + Electron (both are
# Chromium) — only the debugging port differs, so the workflow is identical.
DOM_DUMP_JS = r"""
const PORT = process.argv[2] || '9222';
async function main() {
  let page = null;
  for (let i = 0; i < 20 && !page; i++) {
    try {
      const r = await fetch('http://localhost:' + PORT + '/json');
      const ts = await r.json();
      page = ts.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (e) {}
    if (!page) await new Promise(r => setTimeout(r, 250));
  }
  if (!page) { console.log('[]'); return; }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const expr = `JSON.stringify(
    [...document.querySelectorAll('button,a,input,select,textarea,[role=button],[role=link],[onclick]')]
      .filter(el => {
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetParent !== null;
      })
      .map(el => (el.innerText || el.value || el.getAttribute('aria-label') ||
                  el.getAttribute('placeholder') || el.getAttribute('title') || '').trim())
      .filter(Boolean)
  )`;
  const done = (out) => { try { ws.close(); } catch (e) {} console.log(out); process.exit(0); };
  ws.addEventListener('open', () => ws.send(JSON.stringify(
    { id: 1, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true } })));
  ws.addEventListener('message', (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.id === 1) { try { done(m.result.result.value || '[]'); } catch (e) { done('[]'); } }
  });
  ws.addEventListener('error', () => done('[]'));
  setTimeout(() => done('[]'), 6000);
}
main();
"""


def dom_labels(sandbox, port: int) -> list[str]:
    """Enumerate visible interactive-element labels from the live DOM via CDP.

    Degrades to [] on any failure (no node, CDP down, parse error) so the oracle
    simply no-ops rather than breaking the run.
    """
    try:
        sandbox.write_file("/home/user/dom_dump.cjs", DOM_DUMP_JS)
        res = sandbox.run_sync(
            f"N=$(command -v node || echo {_NODE_FALLBACK}); "
            f'"$N" /home/user/dom_dump.cjs {port} 2>/dev/null || echo "[]"',
            timeout=20,
        )
    except Exception:
        return []
    out = res.stdout.strip() if res and getattr(res, "stdout", "") else "[]"
    # node may emit warnings before our line — take the last line that looks like a list
    line = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("[")), "[]")
    try:
        data = json.loads(line)
    except Exception:
        return []
    return [str(x).strip() for x in data if str(x).strip()]


# One-shot DETERMINISTIC audit over CDP: inject axe-core (from CDN), then read three
# structured signals straight off the live DOM — WCAG violations, images that failed
# to load (naturalWidth=0), and form inputs with no accessible label. These are facts,
# not vision judgments — the strongest evidence tier (parity with ui-test `browse eval`).
# `awaitPromise` lets the in-page async IIFE finish (axe loads + runs) before we read.
DOM_AUDIT_JS = r"""
const PORT = process.argv[2] || '9222';
const EXPR = `(async () => {
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
        s.onload = res; s.onerror = rej;
        document.head.appendChild(s);
        setTimeout(rej, 6000);
      });
    }
    if (window.axe) {
      const r = await window.axe.run(document, { resultTypes: ['violations'] });
      out.axe_violations = r.violations.map(v => ({
        id: v.id, impact: v.impact, help: v.help, nodes: (v.nodes || []).length }));
    }
  } catch (e) { out.axe_error = String(e); }
  return JSON.stringify(out);
})()`;
async function main() {
  let page = null;
  for (let i = 0; i < 20 && !page; i++) {
    try {
      const r = await fetch('http://localhost:' + PORT + '/json');
      const ts = await r.json();
      page = ts.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (e) {}
    if (!page) await new Promise(r => setTimeout(r, 250));
  }
  if (!page) { console.log('{}'); return; }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const done = (out) => { try { ws.close(); } catch (e) {} console.log(out); process.exit(0); };
  ws.addEventListener('open', () => ws.send(JSON.stringify(
    { id: 1, method: 'Runtime.evaluate',
      params: { expression: EXPR, returnByValue: true, awaitPromise: true } })));
  ws.addEventListener('message', (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.id === 1) { try { done(m.result.result.value || '{}'); } catch (e) { done('{}'); } }
  });
  ws.addEventListener('error', () => done('{}'));
  setTimeout(() => done('{}'), 15000);
}
main();
"""


def audit_dom(sandbox, port: int) -> dict:
    """Run the deterministic DOM audit via CDP; return its structured signals.

    Returns {axe_violations, broken_images, unlabeled_inputs} (keys may be absent
    on partial failure). Degrades to {} on any failure (no node, CDP down, axe CDN
    unreachable, parse error) so the audit simply no-ops rather than breaking a run.
    """
    try:
        sandbox.write_file("/home/user/dom_audit.cjs", DOM_AUDIT_JS)
        res = sandbox.run_sync(
            f"N=$(command -v node || echo {_NODE_FALLBACK}); "
            f'"$N" /home/user/dom_audit.cjs {port} 2>/dev/null || echo "{{}}"',
            timeout=35,
        )
    except Exception:
        return {}
    out = res.stdout.strip() if res and getattr(res, "stdout", "") else "{}"
    line = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("{")), "{}")
    try:
        data = json.loads(line)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
