"""Integration tests for the deterministic-audit wiring — fakes, no sandbox/CDP.

Exercises the real glue (cdp parsing/degradation, adapter hooks, Session.audit
ingestion + dedup, autopilot hook) rather than just the pure helpers, plus a real
`node --check` on the embedded CDP scripts so a JS typo can't ship silently.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from inspector.adapters import cdp
from inspector.adapters.base import SurfaceAdapter
from inspector.adapters.web import WebAdapter
from inspector.session import Session


# --- cdp.audit_dom: parse the node payload, degrade on anything weird ---

class _FakeSandbox:
    def __init__(self, stdout=None, raise_on_run=False):
        self._stdout = stdout
        self._raise = raise_on_run
        self.written = {}

    def write_file(self, path, content):
        self.written[path] = content

    def run_sync(self, cmd, timeout=None):
        if self._raise:
            raise RuntimeError("sandbox down")
        return SimpleNamespace(stdout=self._stdout)


def test_audit_dom_parses_valid_json_payload():
    payload = (
        'some node warning\n'
        '{"axe_violations": [{"id": "image-alt", "impact": "critical", '
        '"help": "h", "nodes": 2}], "broken_images": ["a.png"], "unlabeled_inputs": []}'
    )
    out = cdp.audit_dom(_FakeSandbox(stdout=payload), 9222)
    assert out["broken_images"] == ["a.png"]
    assert out["axe_violations"][0]["id"] == "image-alt"


def test_audit_dom_degrades_to_empty_on_junk():
    assert cdp.audit_dom(_FakeSandbox(stdout="not json at all"), 9222) == {}


def test_audit_dom_degrades_to_empty_on_sandbox_error():
    assert cdp.audit_dom(_FakeSandbox(raise_on_run=True), 9222) == {}


def test_audit_dom_writes_the_script_and_passes_the_port():
    sb = _FakeSandbox(stdout="{}")
    cdp.audit_dom(sb, 9333)
    assert "/home/user/dom_audit.cjs" in sb.written
    # the runner is invoked with the requested debugging port


# --- adapter hooks: base no-ops, web delegates to cdp with its port ---

def test_base_adapter_audit_dom_is_empty_default():
    assert SurfaceAdapter.audit_dom(SimpleNamespace()) == {}


def test_web_adapter_delegates_to_cdp(monkeypatch):
    seen = {}

    def fake_cdp_audit(sandbox, port):
        seen["sandbox"], seen["port"] = sandbox, port
        return {"broken_images": ["x.png"]}

    monkeypatch.setattr(cdp, "audit_dom", fake_cdp_audit)
    fake = SimpleNamespace(sandbox="SBX")
    out = WebAdapter.audit_dom(fake)
    assert out == {"broken_images": ["x.png"]}
    assert seen["sandbox"] == "SBX"
    assert seen["port"] == 9222  # CDP_PORT


# --- Session.audit: ingest audit issues as findings, with dedup ---

class _Trace:
    def __init__(self):
        self.findings_dir = "/nonexistent"
        self.saved = []

    def save_finding(self, f):
        self.saved.append(f)


class _Rec:
    id = "ses_x"
    trace_id = "trc_x"

    def __init__(self):
        self.findings = []


def _fake_session(audit_dict):
    s = SimpleNamespace()
    s.touch = lambda: None
    s.adapter = SimpleNamespace(audit_dom=lambda: audit_dict)
    s.trace = _Trace()
    s.record = _Rec()
    s._seen_findings = set()
    s.action_log = []
    s._capture_lock = threading.Lock()  # audit() serializes adapter access via this
    return s


_AUDIT = {
    "axe_violations": [
        {"id": "color-contrast", "impact": "serious", "help": "h", "nodes": 1}
    ],
    "broken_images": ["logo.png"],
    "unlabeled_inputs": ["email"],
}


def test_session_audit_ingests_findings():
    s = _fake_session(_AUDIT)
    audit, new_ids = Session.audit(s)
    assert audit == _AUDIT
    assert len(new_ids) == 3            # 1 axe + broken-images + form-labels
    assert s.record.findings == new_ids  # recorded onto the session
    assert len(s.trace.saved) == 3


def test_session_audit_dedups_on_repeat():
    s = _fake_session(_AUDIT)
    Session.audit(s)
    _, second = Session.audit(s)         # same audit again
    assert second == []                  # nothing new — signatures already seen
    assert len(s.record.findings) == 3


def test_session_audit_noops_on_empty():
    s = _fake_session({})
    audit, new_ids = Session.audit(s)
    assert audit == {} and new_ids == []


def test_session_audit_swallows_adapter_error():
    s = _fake_session(None)
    s.adapter = SimpleNamespace(audit_dom=_raise)
    audit, new_ids = Session.audit(s)
    assert audit == {} and new_ids == []


def _raise():
    raise RuntimeError("CDP exploded")


# --- autopilot hook: runs the audit, never lets it break the run ---

def test_autopilot_run_dom_audit_calls_session_audit():
    from inspector.autopilot import _run_dom_audit

    calls = []
    _run_dom_audit(SimpleNamespace(audit=lambda: calls.append(1)))
    assert calls == [1]


def test_autopilot_run_dom_audit_is_guarded():
    from inspector.autopilot import _run_dom_audit

    # an audit that throws must not propagate (autonomous run keeps its findings)
    _run_dom_audit(SimpleNamespace(audit=_raise))


# --- the embedded CDP JavaScript actually parses (real node --check) ---

@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", ["DOM_AUDIT_JS", "DOM_DUMP_JS", "CDP_LISTENER_JS"])
def test_embedded_cdp_scripts_are_valid_js(tmp_path, name):
    from inspector.adapters import web

    src = getattr(cdp, name, None) or getattr(web, name)
    f = tmp_path / f"{name}.cjs"
    f.write_text(src)
    res = subprocess.run(
        ["node", "--check", str(f)], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr


# --- the BROWSER-SIDE audit logic actually detects, run under node + a DOM stub ---

def _extract_audit_expr() -> str:
    """Pull the in-page `EXPR` (the async IIFE) out of DOM_AUDIT_JS."""
    src = cdp.DOM_AUDIT_JS
    start = src.index("const EXPR = `") + len("const EXPR = `")
    end = src.index("`;", start)
    return src[start:end]


# A minimal DOM: one broken image + one good one; an unlabeled input, an aria-labelled
# one (ok), and a hidden one (ignored). axe-core "load" fails → violations stay empty.
_DOM_STUB = r"""
const inputs = [
  { type:'text', name:'email', id:'', getAttribute:() => null, closest:() => null },
  { type:'text', name:'q', id:'', getAttribute:(a) => a==='aria-label' ? 'Search' : null, closest:() => null },
  { type:'hidden', name:'csrf', id:'', getAttribute:() => null, closest:() => null },
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
global.window = {};  // no window.axe → axe path skips gracefully
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_side_audit_detects_against_a_dom_stub(tmp_path):
    import json

    harness = (
        _DOM_STUB
        + "\nconst __p = " + _extract_audit_expr() + ";\n"
        + "Promise.resolve(__p).then(s => console.log(s)).catch(e => console.log('ERR '+e));\n"
    )
    f = tmp_path / "audit_harness.cjs"
    f.write_text(harness)
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])

    assert out["broken_images"] == ["broken.png"]      # naturalWidth=0 caught, ok.png not
    assert out["unlabeled_inputs"] == ["email"]         # aria-labelled + hidden excluded
    assert out["axe_violations"] == []                  # axe unavailable → graceful skip
