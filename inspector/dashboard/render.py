"""Render the self-contained `dashboard.html` — one replayable index of every run.

Pure string rendering over the aggregate layer, styled with the shared `theme`
(landing-page fonts + palette). Output is a single static file: it links each row
to that session's existing `index.html` replay, so the whole thing works from
`file://` with no server (the chosen 'static aggregator' shape).
"""

from __future__ import annotations

import html
import json

from ..theme import head_style

_PAGE_CSS = """
.wrap{max-width:1180px;margin:0 auto;padding:40px 28px 80px}
header.top{margin-bottom:36px}
header.top h1{font-size:clamp(30px,4vw,52px);line-height:1.1;margin:10px 0 8px}
header.top .sub{color:var(--muted);font-size:15px;max-width:560px}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:28px 0 8px}
.stat{flex:1 1 150px;min-width:150px}
.stat .n{font-family:var(--font-serif);font-size:32px;line-height:1}
.stat .k{margin-top:6px}
.sevbar{display:flex;gap:6px;align-items:center;margin-top:10px;flex-wrap:wrap}
.section{margin-top:40px}
.section > .label{margin-bottom:14px;display:block}
.recur{display:flex;flex-direction:column;gap:8px}
.recur .row{display:flex;align-items:center;gap:12px;padding:10px 14px;
  background:var(--surface);border:1px solid var(--border)}
.recur .row .count{font-family:var(--font-mono);font-size:11px;color:var(--muted);margin-left:auto}
.toolbar{display:flex;gap:12px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
.search{flex:1 1 280px;background:var(--panel);border:1px solid var(--border-bright);
  color:var(--fg);font-family:var(--font-mono);font-size:13px;padding:9px 12px}
.search:focus{outline:none;border-color:var(--border-hover)}
table{border-collapse:collapse;width:100%;font-size:13px}
thead th{font-family:var(--font-mono);font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
  color:var(--muted-2);text-align:left;padding:8px 12px;border-bottom:1px solid var(--border)}
thead th.sortable{cursor:pointer;user-select:none}
thead th.sortable:hover{color:var(--fg)}
thead th.sort-asc::after{content:" ↑";color:var(--green)}
thead th.sort-desc::after{content:" ↓";color:var(--green)}
tbody td{padding:12px;border-bottom:1px solid var(--border);vertical-align:middle}
tbody td:first-child{white-space:nowrap}
tbody tr{transition:background .12s}
tbody tr:hover{background:var(--surface)}
tbody tr.hl{background:rgba(21,199,141,.12);box-shadow:inset 3px 0 0 var(--green)}
.goal{color:var(--fg);max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sub2{color:var(--faint);font-family:var(--font-mono);font-size:11px}
.replay-link{font-family:var(--font-mono);font-size:12px;letter-spacing:0.04em;white-space:nowrap}
.empty{padding:60px 0;text-align:center;color:var(--muted)}
.foot{margin-top:48px;color:var(--faint);font-size:12px;font-family:var(--font-mono)}
.refresh{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:60;
  display:none;align-items:center;gap:10px;background:var(--surface-2);
  border:1px solid var(--green);padding:8px 14px;font-family:var(--font-mono);font-size:12px;
  box-shadow:0 8px 24px rgba(0,0,0,.5)}
.live-wrap{margin-top:32px;display:none}
.live-card{display:flex;align-items:center;gap:12px;padding:12px 16px;margin-bottom:8px;
  background:var(--surface);border:1px solid var(--green)}
.live-dot{width:9px;height:9px;border-radius:50%;background:var(--green);flex:0 0 auto;
  animation:pulse 1.6s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(21,199,141,.55)}
  70%{box-shadow:0 0 0 9px rgba(21,199,141,0)}100%{box-shadow:0 0 0 0 rgba(21,199,141,0)}}
.live-badge{font-family:var(--font-mono);font-size:11px;letter-spacing:.1em;color:var(--green)}
.live-card .g{color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.live-card .meta2{color:var(--muted);font-family:var(--font-mono);font-size:12px;margin-left:auto;
  flex:0 0 auto}
"""


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _sev_badges(by_sev: dict) -> str:
    parts = []
    for sev in ("critical", "high", "medium", "low"):
        n = by_sev.get(sev, 0)
        if n:
            parts.append(f"<span class='sev-badge sev-{sev}'>{n} {sev[0].upper()}</span>")
    return "".join(parts) or "<span class='sub2'>—</span>"


def _stat_card(n, label) -> str:
    return f"<div class='stat card'><div class='n accent'>{_e(n)}</div><div class='k label'>{_e(label)}</div></div>"


def _recurring_panel(recurring: list[dict]) -> str:
    if not recurring:
        return ""
    rows = []
    for g in recurring[:10]:
        rows.append(
            "<div class='row'>"
            f"<span class='sev-badge sev-{_e(g['severity'])}'>{_e(g['severity'])}</span>"
            f"<span>{_e(g['summary'])}</span>"
            f"<span class='count'>{g['count']}× · {len(g['session_ids'])} sessions</span>"
            "</div>"
        )
    return (
        "<div class='section'><span class='label'>// Recurring across runs</span>"
        "<div class='recur'>" + "".join(rows) + "</div></div>"
    )


def _row(s: dict) -> str:
    passed = s.get("passed")
    sev = s.get("by_severity", {})
    # No explicit run verdict? Derive a real one from severity instead of leaking the
    # lifecycle state ("torn_down") into the verdict column.
    if passed is True:
        dot, verdict = "dot-pass", "pass"
    elif passed is False:
        dot, verdict = "dot-fail", "fail"
    elif s.get("state") == "error":
        dot, verdict = "dot-fail", "error"
    elif sev.get("critical") or sev.get("high"):
        dot, verdict = "dot-fail", "fail"
    elif sum(sev.values()):
        dot, verdict = "dot-unknown", "review"
    else:
        dot, verdict = "dot-pass", "clean"
    replay = s.get("replay_path")
    link = (
        f"<a class='replay-link' href='{_e(replay)}' target='_blank' rel='noopener'>▶ replay</a>"
        if replay else "<span class='sub2'>no replay</span>"
    )
    created = (s.get("created_at") or "")[:19].replace("T", " ")
    alias = s.get("alias")
    ident = (f"<span class='accent'>{_e(alias)}</span> · {_e(s.get('id'))}"
             if alias else _e(s.get("id")))
    search = " ".join(str(x) for x in (
        s.get("id"), alias or "", s.get("surface"), s.get("goal"), verdict, s.get("repo_path")
    )).lower()
    sev_score = (sev.get("critical", 0) * 1000 + sev.get("high", 0) * 100
                 + sev.get("medium", 0) * 10 + sev.get("low", 0))
    return (
        f"<tr id='{_e(s.get('id'))}' data-search='{_e(search)}' data-fail='{1 if passed is False else 0}'>"
        f"<td data-sort='{_e(verdict)}'><span class='dot {dot}'></span> <span class='mono' style='font-size:12px'>{_e(verdict)}</span></td>"
        f"<td data-sort='{_e(s.get('surface'))}'><span class='badge'>{_e(s.get('surface'))}</span></td>"
        f"<td data-sort='{_e((s.get('goal') or '').lower())}'><div class='goal'>{_e(s.get('goal') or '(no goal)')}</div>"
        f"<div class='sub2'>{ident}</div></td>"
        f"<td data-sort='{sev_score}'>{_sev_badges(sev)}</td>"
        f"<td class='mono sub2' data-sort='{s.get('n_actions', 0)}'>{s.get('n_actions', 0)} steps · {s.get('n_frames', 0)} frames</td>"
        f"<td class='sub2' data-sort='{_e(s.get('created_at') or '')}'>{_e(created)}</td>"
        f"<td>{link}</td>"
        "</tr>"
    )


def render_index(summaries: list[dict], stats: dict, recurring: list[dict] | None = None) -> str:
    recurring = recurring or []
    sev = stats.get("by_severity", {})
    pass_rate = stats.get("pass_rate")
    pass_rate_txt = f"{pass_rate}%" if pass_rate is not None else "—"

    p: list[str] = []
    p.append("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    p.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    p.append("<title>Inspector — Test Runs</title>")
    p.append(head_style(_PAGE_CSS))
    p.append("</head><body>")
    p.append("<div id='refresh' class='refresh'>● new runs available "
             "<button class='btn' onclick='location.reload()'>refresh</button></div>")
    p.append("<div class='wrap'>")

    p.append("<header class='top'><span class='label'>// Inspector · Session Dashboard</span>")
    p.append("<h1><em>Replay</em> your agent's <span class='accent'>test runs.</span></h1>")
    p.append("<div class='sub'>Inspector session aggregated in one place, view the replay, "
             "open any bug, and hand the fix straight to your agent.</div>")

    p.append("<div class='stats'>")
    p.append(_stat_card(stats.get("n_sessions", 0), "sessions"))
    p.append(_stat_card(stats.get("findings_total", 0), "findings"))
    p.append(_stat_card(pass_rate_txt, "pass rate"))
    p.append("<div class='stat card'><div class='sevbar'>" + _sev_badges(sev)
             + "</div><div class='k label' style='margin-top:14px'>by severity</div></div>")
    p.append("</div></header>")

    # live feed (populated by JS from /live.json when served; hidden otherwise)
    p.append("<div id='live' class='live-wrap'><span class='label'>// Running now</span>"
             "<div id='live-cards' style='margin-top:12px'></div></div>")

    p.append(_recurring_panel(recurring))

    p.append("<div class='section'><span class='label'>// Runs</span>")
    if summaries:
        p.append("<div class='toolbar'>"
                 "<input id='q' class='search' placeholder='filter by goal, surface, id, repo…' "
                 "oninput='flt()'>"
                 "<button class='btn' id='failBtn' onclick='toggleFail()'>only failures</button>"
                 "</div>")
        p.append("<table><thead><tr>"
                 "<th class='sortable' onclick='sortBy(this)'>verdict</th>"
                 "<th class='sortable' onclick='sortBy(this)'>surface</th>"
                 "<th class='sortable' onclick='sortBy(this)'>goal</th>"
                 "<th class='sortable' data-type='num' onclick='sortBy(this)'>findings</th>"
                 "<th class='sortable' data-type='num' onclick='sortBy(this)'>activity</th>"
                 "<th class='sortable' onclick='sortBy(this)'>created</th>"
                 "<th>replay</th>"
                 "</tr></thead><tbody id='rows'>")
        p.append("".join(_row(s) for s in summaries))
        p.append("</tbody></table>")
    else:
        p.append("<div class='empty'>No sessions yet. Run <span class='mono accent'>test_app</span> "
                 "or a <span class='mono accent'>run_test_session</span> loop, then rebuild the dashboard.</div>")
    p.append("</div>")

    p.append("<div class='foot'>generated by inspector.dashboard · static aggregator over "
             "~/.inspector/sessions</div>")
    p.append("</div>")

    p.append(f"<script>window.__INSP_COUNT__={int(stats.get('n_sessions', 0))};</script>")
    p.append("<script>" + _JS + "</script>")
    p.append("</body></html>")
    return "".join(p)


_JS = r"""
let failOnly = false;
function flt(){
  const q = (document.getElementById('q').value || '').toLowerCase();
  localStorage.setItem('insp_q', q);
  document.querySelectorAll('#rows tr').forEach(tr => {
    const hit = tr.dataset.search.includes(q);
    const failOk = !failOnly || tr.dataset.fail === '1';
    tr.style.display = (hit && failOk) ? '' : 'none';
  });
}
function applyFailStyle(){
  const b = document.getElementById('failBtn');
  b.style.borderColor = failOnly ? 'var(--red)' : '';
  b.style.color = failOnly ? 'var(--fg)' : '';
}
function toggleFail(){
  failOnly = !failOnly;
  localStorage.setItem('insp_fail', failOnly ? '1' : '0');
  applyFailStyle();
  flt();
}

// click a column header to sort; click again to reverse
let sortCol = -1, sortDir = 1;
function sortBy(th){
  const idx = th.cellIndex, numeric = th.dataset.type === 'num';
  sortDir = (sortCol === idx) ? -sortDir : 1;
  sortCol = idx;
  const tb = document.getElementById('rows');
  const rows = [...tb.querySelectorAll('tr')];
  const key = tr => { const c = tr.cells[idx]; return (c && c.dataset.sort) || (c ? c.textContent.trim() : ''); };
  rows.sort((a, b) => {
    const av = key(a), bv = key(b);
    const r = numeric ? (parseFloat(av) || 0) - (parseFloat(bv) || 0) : String(av).localeCompare(String(bv));
    return r * sortDir;
  });
  rows.forEach(r => tb.appendChild(r));
  document.querySelectorAll('thead th').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
  th.classList.add(sortDir > 0 ? 'sort-asc' : 'sort-desc');
}

// restore the last search + failures filter across reloads
function restoreFilters(){
  const q = document.getElementById('q');
  if(q) q.value = localStorage.getItem('insp_q') || '';
  failOnly = localStorage.getItem('insp_fail') === '1';
  applyFailStyle();
  flt();
}
// press "/" anywhere to jump to the search box
document.addEventListener('keydown', e => {
  const q = document.getElementById('q');
  if(e.key === '/' && q && document.activeElement !== q){ e.preventDefault(); q.focus(); }
});

// deep-link: dashboard.html#<session_id> scrolls to + highlights that run
function highlightHash(){
  const id = decodeURIComponent((location.hash || '').slice(1));
  if(!id) return;
  const row = document.getElementById(id);
  if(row){ row.classList.add('hl'); row.scrollIntoView({block:'center', behavior:'smooth'}); }
}
window.addEventListener('hashchange', highlightHash);

// relative time: turns the "created" column + live elapsed into ticking "x ago"
function ago(iso){
  const t = new Date(String(iso).replace(' ', 'T')).getTime();
  if(isNaN(t)) return '';
  let s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if(s < 60) return s + 's ago';
  if(s < 3600) return Math.floor(s/60) + 'm ago';
  if(s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
}
function elapsed(iso){
  const t = new Date(String(iso).replace(' ', 'T')).getTime();
  if(isNaN(t)) return '';
  let s = Math.max(0, Math.round((Date.now() - t) / 1000));
  const m = Math.floor(s/60); return (m ? m + 'm ' : '') + (s % 60) + 's';
}
function tickTimes(){
  // only the created column carries an ISO timestamp in data-sort
  document.querySelectorAll('#rows td[data-sort]').forEach(td => {
    const v = td.dataset.sort || '';
    if(/^\d{4}-\d\d-\d\d/.test(v)){ td.title = v; td.textContent = ago(v); }
  });
  document.querySelectorAll('.live-card .el').forEach(e => { e.textContent = elapsed(e.dataset.ts); });
}
setInterval(tickTimes, 1000);

// LIVE feed: poll /live.json (served mode) for in-progress runs; show pulsing cards;
// when a run finishes (live → empty) reload to fold its finished row + stats in.
let wasLive = false;
async function pollLive(){
  let live = [];
  try{
    const r = await fetch('live.json', {cache:'no-store'});
    live = ((await r.json()).sessions) || [];
  }catch(e){ return; }  // file:// or no server → no live feed
  const wrap = document.getElementById('live'), cards = document.getElementById('live-cards');
  if(live.length){
    cards.innerHTML = live.map(s => {
      const name = s.alias || s.id;
      return "<div class='live-card'><span class='live-dot'></span>"
        + "<span class='live-badge'>RUNNING</span>"
        + "<span class='badge'>" + (s.surface || '') + "</span>"
        + "<span class='g'>" + (s.goal || name) + "</span>"
        + "<span class='meta2'>" + (s.findings || 0) + " findings · " + (s.frames || 0)
        + " frames · <span class='el' data-ts='" + (s.created_at || '') + "'></span></span></div>";
    }).join('');
    wrap.style.display = 'block';
    tickTimes();
  } else {
    cards.innerHTML = ''; wrap.style.display = 'none';
  }
  if(wasLive && !live.length){ setTimeout(() => location.reload(), 800); }  // a run just finished
  wasLive = live.length > 0;
}
setInterval(pollLive, 2500);

// auto-refresh: poll dashboard.json; banner appears when a new run lands (served mode)
async function pollNew(){
  try{
    const r = await fetch('dashboard.json', {cache:'no-store'});
    const j = await r.json();
    const n = (j.sessions || []).length;
    if(typeof window.__INSP_COUNT__ === 'number' && n > window.__INSP_COUNT__){
      const b = document.getElementById('refresh'); if(b) b.style.display = 'flex';
    }
  }catch(e){ /* file:// or offline — polling just no-ops */ }
}
setInterval(pollNew, 10000);

document.addEventListener('DOMContentLoaded', () => {
  restoreFilters(); highlightHash(); tickTimes(); pollLive();
});
"""
