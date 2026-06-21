"""One page for a whole parallel run: the plan, every agent's screenshots (thumbnail +
link to its full replay), and the merged findings — so a fan-out resurfaces as a single
view instead of N disconnected runs.
"""
from __future__ import annotations

import html
import os

_CSS = """
:root{--bg:#0e1116;--panel:#161b22;--panel2:#1c232d;--border:#2a323d;--fg:#e6edf3;
--muted:#9aa7b4;--accent:#4493f8;--green:#3fb950;--red:#f85149;--amber:#d29922;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font-family:system-ui,-apple-system,sans-serif;font-size:14px}
.wrap{max-width:1080px;margin:0 auto;padding:28px 32px}
h1{font-size:24px;margin:0 0 2px}.sub{color:var(--muted);margin:0 0 22px}
h2{font-size:15px;margin:26px 0 12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.plan{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.plan li{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:8px 12px;max-width:320px}
.plan b{color:var(--fg)}.plan span{color:var(--muted)}
.agents{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.agent{display:block;text-decoration:none;color:inherit;background:var(--panel);
border:1px solid var(--border);border-radius:12px;overflow:hidden;transition:border-color .15s}
.agent:hover{border-color:var(--accent)}
.thumb{width:100%;height:150px;object-fit:cover;object-position:top;background:#fff;display:block;border-bottom:1px solid var(--border)}
.thumb.empty{display:flex;align-items:center;justify-content:center;color:var(--muted);height:150px}
.meta{padding:11px 13px}.name{font-weight:600;margin-bottom:6px}
.r{display:flex;align-items:center;gap:8px}.muted{color:var(--muted);font-size:12px}
.pill{font-size:11px;padding:2px 8px;border-radius:10px;background:var(--panel2);color:var(--muted)}
.pill.ok{background:rgba(63,185,80,.18);color:var(--green)}
.pill.error{background:rgba(248,81,73,.18);color:var(--red)}
.findings{list-style:none;padding:0;margin:0}
.findings li{background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--amber);
border-radius:8px;padding:10px 13px;margin-bottom:8px}
.sev{font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:8px;font-family:ui-monospace,monospace}
.sev.critical,.sev.high{background:rgba(248,81,73,.18);color:var(--red)}
.sev.medium{background:rgba(210,153,34,.18);color:var(--amber)}
.sev.low,.sev.info{background:var(--panel2);color:var(--muted)}
"""


def _last_frame(session_dir: str) -> str | None:
    fdir = os.path.join(session_dir, "frames")
    if os.path.isdir(fdir):
        frames = sorted(f for f in os.listdir(fdir) if f.endswith(".png"))
        if frames:
            return frames[-1]
    return None


def _sev(s: str) -> str:
    s = (s or "info").lower()
    return f'<span class="sev {html.escape(s)}">{html.escape(s.upper())}</span>'


def write_parallel_report(trace_root: str, plan: list[dict], parts: list[dict],
                          merged: list[dict], group_id: str | None = None) -> str:
    """Render the grouped run page → trace_root/parallel-<id>/index.html (returns the path).
    Links are relative (../<session_id>/…) so it sits alongside the per-agent replays."""
    group_id = group_id or (parts[0].get("session_id", "group") if parts else "group")
    out_dir = os.path.join(trace_root, f"parallel-{group_id}")
    os.makedirs(out_dir, exist_ok=True)

    cards = []
    for p in parts:
        sid = p.get("session_id", "")
        last = _last_frame(os.path.join(trace_root, sid))
        thumb = (f'<img class="thumb" src="../{sid}/frames/{last}" alt="" />' if last
                 else '<div class="thumb empty">no frames</div>')
        status = p.get("status", "?")
        pill = "ok" if status == "ok" else ("error" if status == "error" else "")
        cards.append(
            f'<a class="agent" href="../{sid}/index.html">{thumb}'
            f'<div class="meta"><div class="name">{html.escape(str(p.get("part", "agent")))}</div>'
            f'<div class="r"><span class="pill {pill}">{html.escape(str(status))}</span>'
            f'<span class="muted">{p.get("steps", "?")} steps · '
            f'{p.get("findings_total", 0)} findings</span></div></div></a>'
        )

    plan_html = "".join(
        f'<li><b>{html.escape(pl.get("name", ""))}</b><br>'
        f'<span>{html.escape((pl.get("goal", "") or "")[:120])}</span></li>' for pl in plan
    ) or '<li class="muted">no plan</li>'

    flist = "".join(
        f'<li>{_sev(f.get("severity"))}{html.escape((f.get("summary") or "")[:150])}'
        f'<span class="muted"> {html.escape(f.get("suspected_area", "") or "")}</span></li>'
        for f in merged
    ) or '<li class="muted">No findings surfaced.</li>'

    page = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<title>Parallel run · {len(parts)} agents</title><style>{_CSS}</style></head><body>'
        f'<div class="wrap"><h1>Parallel run · {len(parts)} agents</h1>'
        f'<p class="sub">{len(merged)} unique findings · headless fan-out, one agent per part</p>'
        f'<h2>Plan</h2><ul class="plan">{plan_html}</ul>'
        f'<h2>Agents (click a card for its full replay)</h2><div class="agents">{"".join(cards)}</div>'
        f'<h2>Merged findings</h2><ul class="findings">{flist}</ul>'
        f'</div></body></html>'
    )
    path = os.path.join(out_dir, "index.html")
    with open(path, "w") as f:
        f.write(page)
    return path
