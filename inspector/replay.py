"""Minimal self-contained replay over a session's trace folder.

Seed of the local dashboard (docs/07): pure rendering over the on-disk trace
format (docs/06) — frames + actions.jsonl + findings. Produces:
  - index.html  (frame strip + actions table + findings, embeds the video)
  - replay.gif  (always)
  - replay.mp4  (if ffmpeg is on PATH)
"""

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import tempfile

from .theme import head_style

# Replay-specific styling only — palette/fonts/badges/buttons come from the shared
# theme (theme.BASE_CSS), so the replay matches the dashboard + landing page.
_REPLAY_CSS = """
header.rhead{padding:24px 28px;border-bottom:1px solid var(--border)}
header.rhead h1{font-size:24px}
.rtop{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.verdict{font-family:var(--font-mono);font-size:12px;font-weight:600;letter-spacing:0.08em;
  text-transform:uppercase;padding:5px 12px;border:1px solid currentColor;border-radius:3px;white-space:nowrap}
.verdict-pass,.verdict-clean{color:var(--green)}
.verdict-fail{color:var(--red)}
.verdict-review{color:var(--sev-high)}
.clean{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--green);
  padding:16px;color:var(--muted);font-size:14px}
.fhandoff{display:flex;gap:8px;margin-top:10px;align-items:center;flex-wrap:wrap}
.fhandoff button{font-size:11px;padding:4px 9px}
.fhandoff a.dlink{font-family:var(--font-mono);font-size:11px;color:var(--green);text-decoration:none}
.meta{color:var(--muted);font-size:13px;margin-top:6px}
.section{padding:18px 28px}
.section > .label{display:block;margin-bottom:12px}
.media video,.media img{width:100%;max-width:460px;border:1px solid var(--border);background:#fff;display:block}
.frames{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px}
.frame{flex:0 0 auto;width:260px}
.frame img{width:260px;border:1px solid var(--border);display:block;background:#fff}
.frame .cap{font-size:11px;color:var(--muted);margin-top:4px;font-family:var(--font-mono)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid var(--border);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--surface);font-family:var(--font-mono);font-size:11px;letter-spacing:0.06em}
.finding{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--sev-medium);padding:12px;margin-bottom:10px;cursor:pointer}
.finding:hover{border-color:var(--border-hover)}
code{background:#0b0d12;padding:1px 4px;color:#a8d4ff;font-family:var(--font-mono)}
.annbar{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
button{font-family:var(--font-mono);font-size:13px;background:var(--panel);color:var(--fg);border:1px solid var(--border-bright);padding:6px 11px;cursor:pointer}
button:hover{border-color:var(--border-hover)}
.hint{color:var(--muted-2);font-size:12px}
.overlay{position:relative;display:inline-block;line-height:0;cursor:crosshair}
.overlay img{max-width:460px;display:block;border:1px solid var(--border);background:#fff}
.marker{position:absolute;border:2px solid var(--sev-medium);box-sizing:border-box}
.marker .tag{position:absolute;top:-17px;left:-1px;font-size:11px;color:#0b0d12;padding:1px 6px;white-space:nowrap;font-weight:600;font-family:var(--font-mono)}
.marker.user{border-style:dashed}
.metabox{background:#0b0d12;padding:12px;max-height:300px;overflow:auto;font-size:12px;white-space:pre-wrap;color:#a8d4ff;font-family:var(--font-mono)}
.wrap{max-width:920px;margin:0 auto}
.back{display:inline-block;font-family:var(--font-mono);font-size:12px;letter-spacing:0.04em;
  color:var(--muted);border:1px solid var(--border-bright);padding:6px 11px;margin:0 28px 14px;
  transition:border-color .15s,color .15s}
.back:hover{border-color:var(--border-hover);color:var(--green);text-decoration:none}
.summary{display:flex;gap:8px;flex-wrap:wrap;padding:0 28px}
.chip{font-family:var(--font-mono);font-size:11px;color:var(--muted);border:1px solid var(--border-bright);padding:3px 9px}
.player{width:100%;max-width:820px}
#stage{position:relative;display:block;line-height:0;width:100%}
#stage img{width:100%;display:block;border:1px solid var(--border);background:#fff}
.cursor{position:absolute;pointer-events:none;z-index:6}
.cursor .arw{width:0;height:0;border-left:11px solid #fff;border-top:7px solid transparent;border-bottom:7px solid transparent;filter:drop-shadow(0 0 1px var(--green))}
.cursor .lab{position:absolute;left:13px;top:-3px;background:var(--green);color:#111;font-family:var(--font-mono);font-size:11px;padding:1px 6px;white-space:nowrap}
.controls{display:flex;gap:8px;align-items:center;margin:12px 0 4px;width:100%}
.controls .frameLabel{font-family:var(--font-mono);font-size:12px;color:var(--muted);margin-left:auto;white-space:nowrap}
input[type=range]{flex:1;accent-color:var(--green);height:4px}
.track{position:relative;height:24px;width:100%;border-bottom:1px solid var(--border);margin-bottom:6px;cursor:pointer}
.khint{font-family:var(--font-mono);font-size:11px;color:var(--faint);margin-top:8px;width:100%}
.khint kbd{background:var(--panel);border:1px solid var(--border-bright);border-radius:3px;padding:0 5px;color:var(--muted);font-size:10px}
.track .axis{position:absolute;top:0;left:0;right:0;font-family:var(--font-mono);font-size:10px;color:var(--faint);padding-top:11px}
.tmark{position:absolute;top:3px;width:11px;height:11px;border-radius:50%;transform:translateX(-50%);
  cursor:pointer;border:1px solid #111;box-shadow:0 0 0 2px rgba(0,0,0,.4)}
.tmark:hover{transform:translateX(-50%) scale(1.3)}
.pop{position:fixed;z-index:50;max-width:300px;background:var(--surface-2);border:1px solid var(--border-bright);
  padding:10px 12px;font-size:12px;line-height:1.45;box-shadow:0 8px 24px rgba(0,0,0,.55)}
.pop .s{font-weight:600;margin-bottom:4px}
.finding .fr{font-family:var(--font-mono);font-size:11px;color:var(--green);margin-left:6px}
details.clip{margin:6px 28px;max-width:340px}
details.clip[open]{margin-bottom:14px}
details.clip video,details.clip img{max-width:340px;width:100%;border:1px solid var(--border);background:#fff;margin-top:8px}
summary{cursor:pointer;color:var(--muted);font-family:var(--font-mono);font-size:12px}
/* Android captures are portrait phone screens — cap the screen + video narrower
   so they don't dominate the page at the wide desktop/web defaults above. */
/* portrait mobile surfaces (android + ios) — keep the tall phone frames compact */
.surface-android .player,.surface-ios .player{max-width:300px}
.surface-android .overlay img,.surface-ios .overlay img{max-width:300px}
.surface-android details.clip,.surface-ios details.clip,
.surface-android details.clip video,.surface-ios details.clip video,
.surface-android details.clip img,.surface-ios details.clip img{max-width:300px}
"""

# Interactive player JS (vanilla): a frame slider with a timeline of error markers
# (popups on hover/click), the click cursor + intent overlay, and finding→frame jumps.
# __DATA__ is replaced with the embedded trace metadata.
_PLAYER_JS = r"""
const DATA = __DATA__;
const F = DATA.frames || [];
const SEV = {critical:'#ff4040', high:'#ff8c42', medium:'#ffd166', low:'#7f9bb3'};
const sc = s => SEV[(s||'').toLowerCase()] || '#9e9e9e';
let cur = F[0] || null, timer = null, popTimer = null;

const beforeAction = {};  // frame -> the action whose BEFORE shot it is (for cursor + intent)
(DATA.actions||[]).forEach(a => { if (a.screenshot_before) beforeAction[a.screenshot_before] = a; });

const idxOf = fr => F.indexOf(fr);
const esc = s => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function intent(a){
  if(!a) return '';
  if(a.type==='type') return 'type "'+(a.text||'')+'"';
  if(a.type==='key') return 'press '+(a.key||'');
  return (a.type||'act').replace('_',' ') + (a.target_id!=null ? (' #'+a.target_id) : '');
}
function frameFindings(fr){ return (DATA.findings||[]).filter(f => (f.screenshot_refs||[])[0] === fr); }

// sorted, de-duped frame indices that carry a finding — for J/K finding navigation
const findingIdx = [...new Set((DATA.findings||[])
  .map(f => idxOf((f.screenshot_refs||[])[0])).filter(i => i >= 0))].sort((a,b) => a-b);
function gotoFinding(dir){
  if(!findingIdx.length) return;
  const c = idxOf(cur);
  let t = dir > 0 ? findingIdx.find(i => i > c)
                  : [...findingIdx].reverse().find(i => i < c);
  if(t === undefined) t = dir > 0 ? findingIdx[0] : findingIdx[findingIdx.length-1];  // wrap
  setIdx(t);
  const ff = frameFindings(F[t])[0]; if(ff) showPop(ff, null);
}
// jump to the frame nearest a click on the timeline track
function trackScrub(e){
  if(e.target.classList.contains('tmark')) return;  // marker handles its own click
  const r = e.currentTarget.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  setIdx(Math.round(pct * (F.length - 1)));
}
// warm the browser cache so scrubbing/playback doesn't flash between frames
function preloadFrames(){ F.forEach(fr => { const im = new Image(); im.src = 'frames/' + fr; }); }

function setIdx(i){ i = Math.max(0, Math.min(i, F.length-1)); cur = F[i]; render(); }
function step(d){ setIdx(idxOf(cur)+d); }
function setFrame(fr){
  const i = idxOf(fr); if(i<0) return;
  setIdx(i); window.scrollTo({top:0, behavior:'smooth'});
  const ff = frameFindings(fr)[0]; if(ff) showPop(ff, null);
}
function togglePlay(){
  const b = document.getElementById('playBtn');
  if(timer){ clearInterval(timer); timer=null; b.textContent='▶ play'; return; }
  b.textContent='❚❚ pause';
  timer = setInterval(() => {
    const i = idxOf(cur);
    if(i >= F.length-1){ clearInterval(timer); timer=null; b.textContent='▶ play'; return; }
    setIdx(i+1);
  }, 900);
}

function drawOverlay(){
  const stage = document.getElementById('stage');
  [...stage.querySelectorAll('.marker,.cursor')].forEach(e => e.remove());
  const img = document.getElementById('frame');
  const nw = img.naturalWidth||1, nh = img.naturalHeight||1;
  frameFindings(cur).forEach(f => {
    const b = f.bbox||[]; if(b.length !== 4) return;
    const d = document.createElement('div'); d.className='marker';
    d.style.left=(b[0]*100)+'%'; d.style.top=(b[1]*100)+'%';
    d.style.width=Math.max((b[2]-b[0])*100,2)+'%'; d.style.height=Math.max((b[3]-b[1])*100,2)+'%';
    d.style.borderColor=sc(f.severity);
    const t=document.createElement('span'); t.className='tag'; t.style.background=sc(f.severity);
    t.textContent=(f.summary||'').slice(0,40); d.appendChild(t); stage.appendChild(d);
  });
  const a = beforeAction[cur];
  if(a && a.coords && a.coords.length>=2){
    const c=document.createElement('div'); c.className='cursor';
    c.style.left=(a.coords[0]/nw*100)+'%'; c.style.top=(a.coords[1]/nh*100)+'%';
    c.innerHTML="<div class='arw'></div><div class='lab'>"+esc(intent(a))+"</div>";
    stage.appendChild(c);
  }
}
function render(){
  if(!cur) return;
  const img = document.getElementById('frame');
  img.onload = drawOverlay; img.src = 'frames/' + cur;
  if(img.complete) drawOverlay();
  const sl = document.getElementById('slider'); if(sl) sl.value = idxOf(cur);
  const a = beforeAction[cur];
  document.getElementById('frameLabel').textContent =
    (idxOf(cur)+1) + '/' + F.length + (a ? ('  ·  ' + intent(a)) : '');
}

function buildTrack(){
  const track = document.getElementById('track'); if(!track) return;
  const n = F.length;
  (DATA.findings||[]).forEach(f => {
    const fr = (f.screenshot_refs||[])[0], i = idxOf(fr); if(i<0) return;
    const m = document.createElement('div'); m.className='tmark';
    m.style.left = (n>1 ? (i/(n-1)*100) : 0) + '%'; m.style.background = sc(f.severity);
    m.title = f.summary || '';
    m.addEventListener('mouseenter', e => showPop(f, e));
    m.addEventListener('mouseleave', hidePopSoon);
    m.addEventListener('click', e => { e.stopPropagation(); setFrame(fr); });
    track.appendChild(m);
  });
}
function showPop(f, e){
  clearTimeout(popTimer);
  const fr = (f.screenshot_refs||[])[0];
  const p = document.getElementById('pop');
  p.innerHTML = "<div class='s' style='color:"+sc(f.severity)+"'>"+esc(f.severity)+" · "+esc(f.summary)+"</div>"
    + (f.expected ? ("<div>expected: "+esc(f.expected)+"</div>") : "")
    + (f.actual ? ("<div>actual: "+esc(f.actual)+"</div>") : "")
    + "<div style='margin-top:5px;color:#9e9e9e'>surfaced at frame "+(idxOf(fr)+1)+" — click to jump</div>";
  p.style.display='block';
  if(e){ p.style.left=Math.min(e.clientX+14, window.innerWidth-320)+'px'; p.style.top=(e.clientY+14)+'px'; }
  else { p.style.left='28px'; p.style.top='90px'; }
}
function hidePopSoon(){ popTimer = setTimeout(() => { document.getElementById('pop').style.display='none'; }, 500); }

// --- finding handoff: copy repro steps / a ready-to-paste fix prompt ---
function flash(btn, msg){ const o = btn.textContent; btn.textContent = msg; setTimeout(() => btn.textContent = o, 1200); }
function copyText(t, btn){
  const done = () => flash(btn, 'copied ✓'), fail = () => flash(btn, 'copy failed');
  if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(t).then(done, fail); }
  else { fail(); }
}
function fixPrompt(f){
  const repro = (f.repro||[]).map((s,i) => (i+1)+'. '+s).join('\n');
  return 'Fix this bug found by Inspector.\n\n'
    + 'Summary: ' + (f.summary||'') + '\n'
    + 'Severity: ' + (f.severity||'') + '\n'
    + (f.expected ? ('Expected: ' + f.expected + '\n') : '')
    + (f.actual ? ('Actual: ' + f.actual + '\n') : '')
    + (repro ? ('Steps to reproduce:\n' + repro + '\n') : '');
}
function copyFix(e, i, btn){ e.stopPropagation(); const f = (DATA.findings||[])[i]; if(f) copyText(fixPrompt(f), btn); }
function copyRepro(e, i, btn){
  e.stopPropagation(); const f = (DATA.findings||[])[i]; if(!f) return;
  copyText((f.repro && f.repro.length) ? f.repro.join('\n') : (f.summary || ''), btn);
}
// launch Devin to fix THIS finding (served via the dashboard; api is one level up)
async function devinFix(e, i, btn){
  e.stopPropagation();
  const f = (DATA.findings||[])[i]; if(!f) return;
  const sid = (DATA.session||{}).id, fid = f.id;
  if(!sid || !fid){ flash(btn, 'no id'); return; }
  btn.disabled = true; btn.textContent = 'starting Devin…';
  try{
    const r = await fetch('../api/devin-fix', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({session_id: sid, finding_id: fid})});
    const j = await r.json();
    if(j.error){ btn.disabled = false; btn.textContent = 'error: ' + j.error; return; }
    btn.outerHTML = "<a class='dlink' href='" + j.devin_url +
      "' target='_blank' rel='noopener'>Devin working ↗</a>";
    if(j.devin_session_id) pollDevin(j.devin_session_id, 0);
  }catch(err){ btn.disabled = false; btn.textContent = 'open via the dashboard server'; }
}
function pollDevin(sid, tries){
  if(tries > 40) return;  // 40 × 15s = 10 min cap
  setTimeout(async () => {
    try{
      const r = await fetch('../api/devin-status', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({devin_session_id: sid})});
      const j = await r.json();
      if(j.pr_url){ alert('Devin opened a PR:\n' + j.pr_url); return; }
    }catch(e){}
    pollDevin(sid, tries + 1);
  }, 15000);
}

document.addEventListener('DOMContentLoaded', () => {
  buildTrack(); render(); preloadFrames();
  const p = document.getElementById('pop');
  p.addEventListener('mouseenter', () => clearTimeout(popTimer));
  p.addEventListener('mouseleave', hidePopSoon);
  const track = document.getElementById('track');
  if(track) track.addEventListener('click', trackScrub);
});

document.addEventListener('keydown', e => {
  if(/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName || '')) return;  // don't hijack typing
  const k = e.key;
  if(k === 'ArrowRight') step(1);
  else if(k === 'ArrowLeft') step(-1);
  else if(k === ' ') togglePlay();
  else if(k === 'Home') setIdx(0);
  else if(k === 'End') setIdx(F.length - 1);
  else if(k === 'j' || k === 'J') gotoFinding(1);
  else if(k === 'k' || k === 'K') gotoFinding(-1);
  else return;
  e.preventDefault();
});
"""


# --- video ---------------------------------------------------------------

# Theme RGB (kept in sync with theme.py): green accent + dark chrome for the caption bar.
_GREEN = (21, 199, 141)
_INK = (17, 17, 17)
_BAR = (24, 24, 24)
_MAX_VIDEO_W = 720  # downscale frames so the replay file stays small


def _intent(action: dict) -> str:
    """A short human label for what the action is trying to do (the click intent)."""
    t = action.get("type", "")
    if t == "type":
        return f'type "{action.get("text", "")}"'
    if t == "key":
        return f"press {action.get('key', '')}"
    tid = action.get("target_id")
    verb = str(t).replace("_", " ") or "act"
    return f"{verb} #{tid}" if tid is not None else verb


def _frame_overlays(session_dir: str, names: list[str]) -> dict:
    """Map each frame name → {caption, cursor, intent} from the action timeline.

    A frame that is an action's BEFORE shot is annotated with where we're about to
    click and what we intend; the AFTER shot is annotated with whether it changed.
    """
    actions = _read_jsonl(os.path.join(session_dir, "actions.jsonl"))
    before, after = {}, {}
    for a in actions:
        if a.get("screenshot_before"):
            before[a["screenshot_before"]] = a
        if a.get("screenshot_after"):
            after[a["screenshot_after"]] = a
    out = {}
    n = len(names)
    for i, name in enumerate(names):
        step = f"step {i + 1}/{n}"
        if name in before:
            a = before[name]
            intent = _intent(a)
            coords = a.get("coords")
            cursor = tuple(coords[:2]) if isinstance(coords, list) and len(coords) >= 2 else None
            out[name] = {"caption": f"{step}  >  {intent}", "cursor": cursor, "intent": intent}
        elif name in after:
            a = after[name]
            result = "changed" if a.get("changed") else "no change"
            out[name] = {"caption": f"{step}  =  {result}", "cursor": None, "intent": ""}
        else:
            out[name] = {"caption": f"{step}  observe", "cursor": None, "intent": ""}
    return out


def _draw_cursor(draw, x: int, y: int, label: str, font) -> None:
    """Draw a pointer arrow at (x, y) with the click-intent label beside it."""
    pts = [(x, y), (x, y + 17), (x + 4, y + 13), (x + 7, y + 19),
           (x + 10, y + 18), (x + 7, y + 12), (x + 12, y + 12)]
    draw.polygon(pts, fill=(255, 255, 255), outline=_GREEN)
    if not label:
        return
    tx, ty, pad = x + 16, y, 4
    try:
        b = draw.textbbox((tx, ty), label, font=font)
        tw, th = b[2] - b[0], b[3] - b[1]
    except Exception:  # pragma: no cover - font without textbbox
        tw, th = len(label) * 6, 11
    draw.rectangle([tx - pad, ty - pad, tx + tw + pad, ty + th + pad], fill=_GREEN)
    draw.text((tx, ty), label, fill=_INK, font=font)


def write_replay_video(
    session_dir: str,
    captions: list[str] | None = None,
    seconds_per_frame: float = 2.0,
) -> str | None:
    """Stitch the trace frames into replay.gif (+ replay.mp4 if ffmpeg present).

    Frames are downscaled (smaller file), captioned with the step's intent, and the
    BEFORE shot of each action gets a cursor arrow + label showing where/what it
    clicked. Returns the mp4 path if produced, else the gif path, else None.
    """
    from PIL import Image, ImageDraw, ImageFont

    frames_dir = os.path.join(session_dir, "frames")
    names = sorted(os.listdir(frames_dir)) if os.path.isdir(frames_dir) else []

    def _open(name):
        return Image.open(os.path.join(frames_dir, name)).convert("RGB")

    # Skip unreadable/truncated frames so one bad PNG can't sink the whole replay.
    good = []
    for name in names:
        try:
            _open(name).load()
            good.append(name)
        except Exception:
            continue
    names = good
    if not names:
        return None

    overlays = _frame_overlays(session_dir, names)
    ow, oh = _open(names[0]).size
    scale = min(1.0, _MAX_VIDEO_W / ow)
    W, H = int(ow * scale), int(oh * scale)
    bar = 40
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        font = None

    composed = []
    for i, name in enumerate(names):
        src = _open(name)
        fw, fh = src.size  # scale this frame's click coords onto the resized canvas
        im = src.resize((W, H))
        canvas = Image.new("RGB", (W, H + bar), _BAR)
        canvas.paste(im, (0, 0))
        draw = ImageDraw.Draw(canvas)

        ov = overlays.get(name, {})
        if ov.get("cursor"):
            cx = int(ov["cursor"][0] * W / fw)
            cy = int(ov["cursor"][1] * H / fh)
            cx = max(0, min(cx, W - 1))
            cy = max(0, min(cy, H - 1))
            _draw_cursor(draw, cx, cy, ov.get("intent", ""), font)

        caption = (
            captions[i] if captions and i < len(captions)
            else ov.get("caption", f"step {i + 1}/{len(names)}")
        )
        draw.text((12, H + 13), caption, fill=(230, 230, 230), font=font)
        composed.append(canvas)

    gif_path = os.path.join(session_dir, "replay.gif")
    composed[0].save(
        gif_path,
        save_all=True,
        append_images=composed[1:],
        duration=int(seconds_per_frame * 1000),
        loop=0,
        optimize=True,
    )
    result = gif_path

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        with tempfile.TemporaryDirectory() as td:
            for i, im in enumerate(composed):
                im.save(os.path.join(td, f"f{i:04d}.png"))
            mp4_path = os.path.join(session_dir, "replay.mp4")
            cmd = [
                ffmpeg, "-y",
                "-framerate", str(1.0 / seconds_per_frame),
                "-i", os.path.join(td, "f%04d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                mp4_path,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                result = mp4_path
            except Exception:
                pass  # incl. TimeoutExpired — keep the GIF, never block on ffmpeg
    return result


# --- html ----------------------------------------------------------------

def write_replay_html(session_dir: str) -> str:
    frames_dir = os.path.join(session_dir, "frames")
    frames = sorted(os.listdir(frames_dir)) if os.path.isdir(frames_dir) else []
    actions = _read_jsonl(os.path.join(session_dir, "actions.jsonl"))
    findings = _read_dir_json(os.path.join(session_dir, "findings"))
    sess = _read_json(os.path.join(session_dir, "session.json"))
    run = _read_json(os.path.join(session_dir, "run.json"))
    media = _media_tag(session_dir)
    out = os.path.join(session_dir, "index.html")
    with open(out, "w") as f:
        f.write(_build_html(sess, frames, actions, findings, media, run))
    return out


def _media_tag(session_dir: str) -> str:
    """The rendered clip as a small, collapsed extra — the scrubber is the primary view."""
    if os.path.exists(os.path.join(session_dir, "replay.mp4")):
        return ("<details class='clip'><summary>▷ rendered clip (mp4)</summary>"
                "<video src='replay.mp4' controls loop muted></video></details>")
    if os.path.exists(os.path.join(session_dir, "replay.gif")):
        return ("<details class='clip'><summary>▷ rendered clip (gif)</summary>"
                "<img src='replay.gif'></details>")
    return ""


def _read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _read_dir_json(d: str) -> list[dict]:
    out: list[dict] = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if n.endswith(".json"):
                out.append(_read_json(os.path.join(d, n)))
    return out


def _read_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _e(x) -> str:
    return html.escape(str(x))


def _frame_index(frames: list, name: str) -> int:
    try:
        return frames.index(name)
    except ValueError:
        return -1


def _verdict(run: dict | None, by_sev: dict[str, int]) -> tuple[str, str]:
    """(css_class, label) for the header pill.

    An explicit run verdict (run.json `passed`) always wins. Absent one, derive a
    real pass/fail from finding severity instead of a wishy-washy 'review': any
    critical/high finding fails the run; lower-severity findings are flagged for
    review; nothing found passes clean.
    """
    n = sum(by_sev.values())
    passed = (run or {}).get("passed")
    if passed is True:
        return "pass", "✓ pass"
    if passed is False:
        return "fail", f"✗ fail · {n} findings" if n else "✗ fail"
    if by_sev.get("critical") or by_sev.get("high"):
        return "fail", f"✗ fail · {n} findings"
    if n:
        return "review", f"⚠ review · {n} findings"
    return "clean", "✓ no findings"


def _build_html(sess, frames, actions, findings, media: str = "", run: dict | None = None) -> str:
    # the trace metadata embedded for the player (slider + timeline + overlays)
    data = {"session": sess, "frames": frames, "findings": findings,
            "actions": actions, "annotations": []}
    # Escape ALL '<' so untrusted finding text can't break out of the <script> via
    # </script> OR an HTML comment open (<!--…<script>…). < is valid in JS strings.
    data_json = json.dumps(data).replace("<", "\\u003c")

    by_sev: dict[str, int] = {}
    for f in findings:
        s = (f.get("severity") or "low").lower()
        by_sev[s] = by_sev.get(s, 0) + 1
    sev_chips = "".join(
        f"<span class='chip sev-{s}'>{by_sev[s]} {s}</span>"
        for s in ("critical", "high", "medium", "low") if by_sev.get(s)
    )
    verdict_cls, verdict_txt = _verdict(run, by_sev)

    p: list[str] = []
    p.append("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    p.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    p.append("<title>Inspector replay — " + _e(sess.get("id", "")) + "</title>")
    surface_cls = " surface-" + "".join(
        c for c in str(sess.get("surface", "")).lower() if c.isalnum()
    )
    p.append(head_style(_REPLAY_CSS) + "</head><body><div class='wrap" + surface_cls + "'>")

    created = (sess.get("created_at") or "")[:19].replace("T", " ")
    p.append("<a class='back' href='../dashboard.html'>← All runs</a>")
    p.append("<header class='rhead'>")
    p.append("<div class='rtop'><span class='label'>// Inspector · Replay</span>"
             "<span class='verdict verdict-" + verdict_cls + "'>" + verdict_txt + "</span></div>")
    p.append("<h1>" + _e(sess.get("goal") or "Session replay") + "</h1>")
    p.append(
        "<div class='meta mono'>" + _e(sess.get("id", "")) + " · " + _e(sess.get("surface", ""))
        + " · " + str(len(frames)) + " frames"
        + (" · " + _e(created) if created else "") + "</div></header>"
    )
    if sev_chips:
        p.append("<div class='summary'>" + sev_chips + "</div>")

    # --- the scrubber: frame slider + cursor/finding overlay + error timeline ---
    if frames:
        last = len(frames) - 1
        bug_nav = (
            "<button onclick='gotoFinding(-1)' title='previous finding (K)'>◆ prev bug</button>"
            "<button onclick='gotoFinding(1)' title='next finding (J)'>next bug ◆</button>"
        ) if findings else ""
        p.append("<div class='section'><span class='label'>// Replay</span>")
        # the player: error-timeline pins sit directly above the video (same width),
        # the playback controls form a bar directly below it.
        p.append("<div class='player'>")
        p.append("<div id='track' class='track' title='click to scrub · markers show where bugs surfaced — hover for the error'>"
                 "<span class='axis'>error timeline — markers show where bugs surfaced</span></div>")
        p.append("<div id='stage'><img id='frame'></div>")
        p.append("<div class='controls'>"
                 "<button onclick='step(-1)' title='previous frame (←)'>◀</button>"
                 "<button id='playBtn' onclick='togglePlay()' title='play/pause (space)'>▶ play</button>"
                 "<button onclick='step(1)' title='next frame (→)'>▶</button>"
                 + bug_nav +
                 f"<input id='slider' type='range' min='0' max='{last}' value='0' "
                 "oninput='setIdx(+this.value)'>"
                 "<span id='frameLabel' class='frameLabel'></span></div>")
        p.append("<div class='khint'><kbd>←</kbd> <kbd>→</kbd> frame · "
                 "<kbd>space</kbd> play · <kbd>J</kbd> <kbd>K</kbd> next/prev bug · "
                 "<kbd>Home</kbd> <kbd>End</kbd> ends · click timeline to scrub</div>")
        p.append("</div>")
        p.append(media)
        p.append("</div>")

    if findings:
        p.append("<div class='section'><span class='label'>// Findings (" + str(len(findings)) + ")</span>")
        # `i` aligns with DATA.findings order so the copy buttons resolve the right one
        for i, f in enumerate(findings):
            frame = (f.get("screenshot_refs") or [""])[0]
            idx = _frame_index(frames, frame) if frame else -1
            fr_label = (f"<span class='fr'>📍 frame {idx + 1}</span>" if idx >= 0 else "")
            onclick = (" onclick=\"setFrame('" + _e(frame) + "')\"") if idx >= 0 else ""
            cursor = " style='cursor:pointer'" if idx >= 0 else ""
            p.append("<div class='finding'" + onclick + cursor + "><span class='badge sev-"
                     + _e((f.get('severity') or 'low').lower()) + "'>"
                     + _e(f.get("severity", "")) + " · " + _e(f.get("confidence", ""))
                     + "</span> <b>" + _e(f.get("summary", "")) + "</b>" + fr_label)
            p.append("<div class='meta'>expected: " + _e(f.get("expected", "")) + "</div>")
            p.append("<div class='meta'>actual: " + _e(f.get("actual", "")) + "</div>")
            if f.get("repro"):
                p.append("<div class='meta'>repro: " + _e(" → ".join(f["repro"])) + "</div>")
            p.append(f"<div class='fhandoff'>"
                     f"<button onclick='copyRepro(event,{i},this)' title='copy the repro steps'>copy repro</button>"
                     f"<button onclick='copyFix(event,{i},this)' title='copy a ready-to-paste fix prompt for a coding agent'>copy fix prompt</button>"
                     f"<button onclick='devinFix(event,{i},this)' title='launch Devin to open a PR fixing this issue'>Fix with Devin</button>"
                     f"</div>")
            p.append("</div>")
        p.append("</div>")
    else:
        p.append("<div class='section'><span class='label'>// Findings (0)</span>"
                 "<div class='clean'>✓ Clean run — no findings surfaced across "
                 + str(len(frames)) + " frames.</div></div>")

    p.append("<div class='section'><span class='label'>// Actions</span><table>")
    p.append("<tr><th>#</th><th>type</th><th>target</th><th>changed</th><th>before → after</th><th>logs</th></tr>")
    for a in actions:
        logs = " ".join(a.get("logs") or [])[:200]
        p.append(
            "<tr><td>" + _e(a.get("seq")) + "</td><td>" + _e(a.get("type"))
            + "</td><td>" + _e(a.get("target_id")) + "</td><td>" + _e(a.get("changed"))
            + "</td><td>" + _e(a.get("screenshot_before")) + " → " + _e(a.get("screenshot_after"))
            + "</td><td><code>" + _e(logs) + "</code></td></tr>"
        )
    p.append("</table></div>")

    p.append("<div id='pop' class='pop' style='display:none'></div>")
    p.append("<script>" + _PLAYER_JS.replace("__DATA__", data_json) + "</script>")
    p.append("</div></body></html>")
    return "".join(p)
