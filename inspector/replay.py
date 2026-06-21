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

_CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:16px 24px;background:#171a21;border-bottom:1px solid #2a2f3a}
h1{font-size:18px;margin:0} h2{font-size:15px;color:#cdd5e0}
.meta{color:#9aa4b2;font-size:13px;margin-top:4px}
.section{padding:16px 24px}
.media img,.media video{max-width:780px;border:1px solid #2a2f3a;border-radius:6px;background:#fff}
.frames{display:flex;gap:12px;overflow-x:auto;padding-bottom:8px}
.frame{flex:0 0 auto;width:380px}
.frame img{width:380px;border:1px solid #2a2f3a;border-radius:6px;display:block;background:#fff}
.frame .cap{font-size:12px;color:#9aa4b2;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #2a2f3a;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#171a21}
.finding{background:#1b1320;border:1px solid #5a2a4a;border-radius:8px;padding:12px;margin-bottom:10px;cursor:pointer}
.finding:hover{border-color:#ff8c42}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;background:#3a2030;color:#ffb4d2}
code{background:#0b0d12;padding:1px 4px;border-radius:4px;color:#a8d4ff}
.annbar{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
button{background:#222834;color:#e6e6e6;border:1px solid #2a2f3a;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:13px}
button:hover{background:#2a3340}
.hint{color:#9aa4b2;font-size:12px}
.overlay{position:relative;display:inline-block;line-height:0;cursor:crosshair}
.overlay img{max-width:420px;display:block;border:1px solid #2a2f3a;border-radius:6px;background:#fff}
.marker{position:absolute;border:2px solid #ffd166;border-radius:4px;box-sizing:border-box}
.marker .tag{position:absolute;top:-17px;left:-1px;font-size:11px;color:#0b0d12;padding:1px 6px;border-radius:6px;white-space:nowrap;font-weight:600}
.marker.user{border-style:dashed}
.metabox{background:#0b0d12;padding:12px;border-radius:6px;max-height:300px;overflow:auto;font-size:12px;white-space:pre-wrap;color:#a8d4ff}
"""

# Interactive annotator JS (vanilla). __DATA__ is replaced with the embedded metadata.
_ANNOTATOR_JS = r"""
const DATA = __DATA__;
const ANN = (DATA.annotations || []);
let cur = DATA.frames[0] || null;
const SEV = {critical:'#ff5470', high:'#ff8c42', medium:'#ffd166', low:'#7fd1ae'};
const sc = s => SEV[(s||'').toLowerCase()] || '#9aa4b2';

function frameFindings(fr){
  return DATA.findings.filter(f => ((f.screenshot_refs||[])[0] === fr) && (f.bbox||[]).length === 4);
}
function setFrame(fr){ if (fr){ cur = fr; render(); window.scrollTo({top:0,behavior:'smooth'}); } }
function step(d){
  const i = DATA.frames.indexOf(cur);
  cur = DATA.frames[Math.min(Math.max(i + d, 0), DATA.frames.length - 1)];
  render();
}
function mk(ov, bbox, sev, label, user){
  const [x1,y1,x2,y2] = bbox;
  const d = document.createElement('div');
  d.className = 'marker' + (user ? ' user' : '');
  d.style.left = (x1*100)+'%'; d.style.top = (y1*100)+'%';
  d.style.width = Math.max((x2-x1)*100, 1.5)+'%'; d.style.height = Math.max((y2-y1)*100, 1.5)+'%';
  d.style.borderColor = sc(sev);
  const t = document.createElement('span'); t.className='tag'; t.textContent = label; t.style.background = sc(sev);
  d.appendChild(t);
  d.addEventListener('click', ev => { ev.stopPropagation(); alert(label); });
  ov.appendChild(d);
}
function render(){
  if (!cur) return;
  document.getElementById('annImg').src = 'frames/' + cur;
  document.getElementById('frameLabel').textContent =
    cur + '  (' + (DATA.frames.indexOf(cur)+1) + '/' + DATA.frames.length + ')';
  const ov = document.getElementById('overlay');
  [...ov.querySelectorAll('.marker')].forEach(m => m.remove());
  frameFindings(cur).forEach(f => mk(ov, f.bbox, f.severity, f.summary, false));
  ANN.filter(a => a.frame === cur).forEach(a => mk(ov, [a.x, a.y, a.x+0.02, a.y+0.02], a.severity, a.label, true));
  meta();
}
function meta(){
  document.getElementById('meta').textContent =
    JSON.stringify({session: DATA.session, findings: DATA.findings, annotations: ANN}, null, 2);
}
function exportMeta(){
  const blob = new Blob([JSON.stringify({session: DATA.session, findings: DATA.findings, annotations: ANN}, null, 2)],
    {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = (DATA.session.id || 'replay') + '-metadata.json'; a.click();
}
document.addEventListener('DOMContentLoaded', () => {
  const ov = document.getElementById('overlay');
  ov.addEventListener('click', e => {
    if (e.target.closest('.marker')) return;
    const r = ov.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    const label = prompt('Label this bug spot:'); if (!label) return;
    const severity = (prompt('Severity (critical/high/medium/low):', 'medium') || 'medium').toLowerCase();
    ANN.push({frame: cur, x: +x.toFixed(4), y: +y.toFixed(4), label, severity});
    render();
  });
  render();
});
"""


# --- video ---------------------------------------------------------------

def write_replay_video(
    session_dir: str,
    captions: list[str] | None = None,
    seconds_per_frame: float = 2.0,
) -> str | None:
    """Stitch the trace frames into replay.gif (+ replay.mp4 if ffmpeg present).

    Each frame is held for `seconds_per_frame` and captioned with its step.
    Returns the mp4 path if produced, else the gif path, else None.
    """
    from PIL import Image, ImageDraw, ImageFont

    frames_dir = os.path.join(session_dir, "frames")
    names = sorted(os.listdir(frames_dir)) if os.path.isdir(frames_dir) else []
    if not names:
        return None

    base = Image.open(os.path.join(frames_dir, names[0])).convert("RGB")
    W, H = base.size
    bar = 44
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        font = None

    composed = []
    for i, name in enumerate(names):
        im = Image.open(os.path.join(frames_dir, name)).convert("RGB").resize((W, H))
        canvas = Image.new("RGB", (W, H + bar), (15, 17, 21))
        canvas.paste(im, (0, 0))
        draw = ImageDraw.Draw(canvas)
        caption = (
            captions[i] if captions and i < len(captions)
            else f"step {i + 1}/{len(names)} — {name}"
        )
        draw.text((12, H + 14), caption, fill=(230, 230, 230), font=font)
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
    media = _media_tag(session_dir)
    out = os.path.join(session_dir, "index.html")
    with open(out, "w") as f:
        f.write(_build_html(sess, frames, actions, findings, media))
    return out


def _media_tag(session_dir: str) -> str:
    if os.path.exists(os.path.join(session_dir, "replay.mp4")):
        return (
            "<div class='section media'><h2>Video</h2>"
            "<video src='replay.mp4' controls autoplay loop muted></video></div>"
        )
    if os.path.exists(os.path.join(session_dir, "replay.gif")):
        return "<div class='section media'><h2>Video</h2><img src='replay.gif'></div>"
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


def _build_html(sess, frames, actions, findings, media: str = "") -> str:
    # the metadata blob embedded in the page (and exported by the annotator)
    data = {"session": sess, "frames": frames, "findings": findings,
            "actions": actions, "annotations": []}
    data_json = json.dumps(data).replace("</", "<\\/")  # safe inside <script>

    p: list[str] = []
    p.append("<!doctype html><html><head><meta charset='utf-8'><title>Inspector replay</title>")
    p.append("<style>" + _CSS + "</style></head><body>")
    p.append("<header><h1>Inspector replay — " + _e(sess.get("id", "")) + "</h1>")
    p.append(
        "<div class='meta'>surface: " + _e(sess.get("surface", ""))
        + " · goal: " + _e(sess.get("goal", ""))
        + " · state: " + _e(sess.get("state", "")) + "</div></header>"
    )

    p.append(media)

    if findings:
        p.append("<div class='section'><h2>Findings (" + str(len(findings)) + ")</h2>")
        for f in findings:
            frame = (f.get("screenshot_refs") or [""])[0]
            pin = " 📍" if f.get("bbox") else ""
            onclick = (" onclick=\"setFrame('" + _e(frame) + "')\"") if frame else ""
            p.append("<div class='finding'" + onclick + "><span class='badge'>"
                     + _e(f.get("severity", "")) + " · " + _e(f.get("confidence", ""))
                     + "</span> <b>" + _e(f.get("summary", "")) + "</b>" + pin)
            p.append("<div class='meta'>expected: " + _e(f.get("expected", "")) + "</div>")
            p.append("<div class='meta'>actual: " + _e(f.get("actual", "")) + "</div>")
            if f.get("repro"):
                p.append("<div class='meta'>repro: " + _e(" → ".join(f["repro"])) + "</div>")
            p.append("</div>")
        p.append("</div>")

    # interactive annotator: click the frame to drop + label a bug marker
    if frames:
        p.append("<div class='section'><h2>Annotator</h2>")
        p.append("<div class='annbar'>"
                 "<button onclick='step(-1)'>◀ prev</button>"
                 "<span id='frameLabel' class='meta'></span>"
                 "<button onclick='step(1)'>next ▶</button>"
                 "<button onclick='exportMeta()'>⬇ Export metadata (JSON)</button>"
                 "<span class='hint'>click anywhere on the frame to drop a labeled bug marker; "
                 "click a 📍 finding above to jump to its frame</span></div>")
        p.append("<div id='overlay' class='overlay'><img id='annImg'></div>")
        p.append("</div>")
        p.append("<div class='section'><h2>Metadata (embedded in this HTML)</h2>"
                 "<pre id='meta' class='metabox'></pre></div>")

    p.append("<div class='section'><h2>Actions</h2><table>")
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

    p.append("<script>" + _ANNOTATOR_JS.replace("__DATA__", data_json) + "</script>")
    p.append("</body></html>")
    return "".join(p)
