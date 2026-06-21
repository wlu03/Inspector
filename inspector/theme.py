"""Shared visual design tokens — the single source of truth for Inspector's UI.

Mirrors the marketing landing page (`web/`): Geist (sans) + Geist Mono (labels/code)
+ Playfair Display (serif headlines), the #111 dot-grid background, the #15C78D green
accent and #ff4040 red. Both the static dashboard (`dashboard/render.py`) and the
per-session replay (`replay.py`) import from here so they never drift apart.
"""

from __future__ import annotations

# Google Fonts that match the landing page's next/font choices.
FONT_IMPORT = (
    '@import url("https://fonts.googleapis.com/css2?'
    "family=Geist:wght@400;500;600&"
    "family=Geist+Mono:wght@400;500&"
    'family=Playfair+Display:ital,wght@0,400;0,700;1,400&display=swap");'
)

# CSS custom properties — the palette + type stacks lifted from web/app/globals.css.
TOKENS = """
:root{
  --bg:#111111; --surface:#1e1e1e; --surface-2:#262626; --panel:#242424;
  --fg:#f0f0f0; --muted:#9e9e9e; --muted-2:#6b6b6b; --faint:#686868;
  --border:#2e2e2e; --border-bright:#3a3a3a; --border-hover:#555555;
  --green:#15C78D; --red:#ff4040;
  --sev-critical:#ff4040; --sev-high:#ff8c42; --sev-medium:#ffd166; --sev-low:#7f9bb3;
  --font-sans:"Geist",system-ui,-apple-system,Segoe UI,sans-serif;
  --font-mono:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --font-serif:"Playfair Display",Georgia,serif;
}
"""

# Shared element styling — body dot-grid, serif headings, mono labels, badges, buttons.
BASE_CSS = """
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background-color:var(--bg);
  background-image:radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px);
  background-size:24px 24px;
  color:var(--fg);font-family:var(--font-sans);-webkit-font-smoothing:antialiased;line-height:1.5}
::selection{background:var(--green);color:#141414}
a{color:var(--green);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3{font-family:var(--font-serif);font-weight:400;letter-spacing:0;margin:0}
em{font-style:italic}
.accent{color:var(--green)}
.muted{color:var(--muted)} .faint{color:var(--faint)}
.mono{font-family:var(--font-mono)}
.label{font-family:var(--font-mono);font-size:11px;letter-spacing:0.15em;
  text-transform:uppercase;color:var(--muted-2)}
.card{background:var(--surface);border:1px solid var(--border);padding:16px}
.badge{display:inline-block;font-family:var(--font-mono);font-size:11px;letter-spacing:0.04em;
  padding:2px 8px;border:1px solid var(--border-bright);color:var(--muted)}
.btn{font-family:var(--font-mono);font-size:12px;letter-spacing:0.05em;background:none;
  color:var(--muted);border:1px solid var(--border-bright);padding:7px 12px;cursor:pointer;
  transition:border-color .15s,color .15s}
.btn:hover{border-color:var(--border-hover);color:var(--fg)}
.sev-badge{display:inline-block;font-family:var(--font-mono);font-size:10px;letter-spacing:0.06em;
  padding:1px 7px;border:1px solid currentColor;border-radius:2px;margin-right:4px}
.sev-critical{color:var(--sev-critical)} .sev-high{color:var(--sev-high)}
.sev-medium{color:var(--sev-medium)} .sev-low{color:var(--sev-low)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%}
.dot-pass{background:var(--green)} .dot-fail{background:var(--red)} .dot-unknown{background:var(--muted-2)}
"""


def head_style(extra_css: str = "") -> str:
    """A complete <style> block: font import + tokens + base + page-specific CSS."""
    return "<style>" + FONT_IMPORT + TOKENS + BASE_CSS + extra_css + "</style>"
