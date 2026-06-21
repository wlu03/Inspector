"""One page for a whole parallel run: the plan, every agent's screenshots (thumbnail +
link to its full replay), and the merged findings — so a fan-out resurfaces as a single
view instead of N disconnected runs.
"""
from __future__ import annotations

import html
import os

from .theme import head_style

# Page-specific styling only — palette, fonts, and shared classes (.label, .card,
# .badge, .sev-badge, .accent) come from the dashboard's `theme` so this report and
# `dashboard/render.py` share one visual language.
_PAGE_CSS = """
.wrap{max-width:1180px;margin:0 auto;padding:40px 28px 80px}
header.top{margin-bottom:8px}
header.top h1{font-size:clamp(30px,4vw,52px);line-height:1.1;margin:10px 0 8px}
header.top .sub{color:var(--muted);font-size:15px;max-width:560px}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:28px 0 8px}
.stat{flex:1 1 150px;min-width:150px}
.stat .n{font-family:var(--font-serif);font-size:32px;line-height:1}
.stat .k{margin-top:6px}
.section{margin-top:40px}
.section > .label{margin-bottom:14px;display:block}
.plan{display:flex;flex-wrap:wrap;gap:10px;margin:0;padding:0;list-style:none}
.plan li{background:var(--surface);border:1px solid var(--border);padding:12px 14px;max-width:340px}
.plan b{font-family:var(--font-mono);font-size:12px;letter-spacing:.04em;color:var(--fg)}
.plan span{color:var(--muted);font-size:13px}
.agents{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.agent{display:block;text-decoration:none;color:inherit;background:var(--surface);
  border:1px solid var(--border);overflow:hidden;transition:border-color .15s}
.agent:hover{border-color:var(--border-hover);text-decoration:none}
.thumb{width:100%;height:150px;object-fit:cover;object-position:top;background:#fff;
  display:block;border-bottom:1px solid var(--border)}
.thumb.empty{display:flex;align-items:center;justify-content:center;color:var(--muted-2);
  height:150px;font-family:var(--font-mono);font-size:12px}
.meta{padding:12px 14px}.name{font-weight:600;margin-bottom:8px}
.r{display:flex;align-items:center;gap:8px}
.r .muted{color:var(--muted);font-family:var(--font-mono);font-size:11px}
.pill{font-family:var(--font-mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 8px;border:1px solid currentColor;border-radius:2px;color:var(--muted-2)}
.pill.ok{color:var(--green)}
.pill.error{color:var(--red)}
.findings{list-style:none;padding:0;margin:0}
.findings li{background:var(--surface);border:1px solid var(--border);
  border-left:3px solid var(--sev-medium);padding:11px 14px;margin-bottom:8px}
.findings .area{color:var(--muted);font-family:var(--font-mono);font-size:11px}
.foot{margin-top:48px;color:var(--faint);font-size:12px;font-family:var(--font-mono)}
"""


def _last_frame(session_dir: str) -> str | None:
    fdir = os.path.join(session_dir, "frames")
    if os.path.isdir(fdir):
        frames = sorted(f for f in os.listdir(fdir) if f.endswith(".png"))
        if frames:
            return frames[-1]
    return None


def _sev(s: str) -> str:
    s = (s or "low").lower()
    return f'<span class="sev-badge sev-{html.escape(s)}">{html.escape(s)}</span>'


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
        f'<span class="area"> {html.escape(f.get("suspected_area", "") or "")}</span></li>'
        for f in merged
    ) or '<li class="muted">No findings surfaced.</li>'

    n_steps = sum(int(p.get("steps", 0) or 0) for p in parts)

    page = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Inspector — Parallel run · {len(parts)} agents</title>'
        f'{head_style(_PAGE_CSS)}</head><body><div class="wrap">'
        f'<header class="top"><span class="label">// Inspector · Parallel Run</span>'
        f'<h1><em>Fan-out</em> across <span class="accent">{len(parts)} agents.</span></h1>'
        f'<div class="sub">One scout mapped the app into parts; an autonomous agent '
        f'traversed each in parallel, and their findings are merged below.</div>'
        f'<div class="stats">'
        f'<div class="stat card"><div class="n accent">{len(parts)}</div><div class="k label">agents</div></div>'
        f'<div class="stat card"><div class="n accent">{len(merged)}</div><div class="k label">unique findings</div></div>'
        f'<div class="stat card"><div class="n accent">{n_steps}</div><div class="k label">total steps</div></div>'
        f'</div></header>'
        f'<div class="section"><span class="label">// Plan</span><ul class="plan">{plan_html}</ul></div>'
        f'<div class="section"><span class="label">// Agents · click a card for its full replay</span>'
        f'<div class="agents">{"".join(cards)}</div></div>'
        f'<div class="section"><span class="label">// Merged findings</span>'
        f'<ul class="findings">{flist}</ul></div>'
        f'<div class="foot">generated by inspector.parallel_report · headless fan-out, one agent per part</div>'
        f'</div></body></html>'
    )
    path = os.path.join(out_dir, "index.html")
    with open(path, "w") as f:
        f.write(page)
    return path
