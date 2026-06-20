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
.finding{background:#1b1320;border:1px solid #5a2a4a;border-radius:8px;padding:12px;margin-bottom:10px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;background:#3a2030;color:#ffb4d2}
code{background:#0b0d12;padding:1px 4px;border-radius:4px;color:#a8d4ff}
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
        p.append("<div class='section'><h2>Findings</h2>")
        for f in findings:
            p.append(
                "<div class='finding'><span class='badge'>" + _e(f.get("severity", ""))
                + " · " + _e(f.get("confidence", "")) + "</span> <b>"
                + _e(f.get("summary", "")) + "</b>"
            )
            p.append("<div class='meta'>expected: " + _e(f.get("expected", "")) + "</div>")
            p.append("<div class='meta'>actual: " + _e(f.get("actual", "")) + "</div>")
            if f.get("repro"):
                p.append("<div class='meta'>repro: " + _e(" → ".join(f["repro"])) + "</div>")
            p.append("</div>")
        p.append("</div>")

    p.append("<div class='section'><h2>Frames (" + str(len(frames)) + ")</h2><div class='frames'>")
    for fr in frames:
        p.append("<div class='frame'><img src='frames/" + _e(fr) + "'><div class='cap'>" + _e(fr) + "</div></div>")
    p.append("</div></div>")

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
    p.append("</table></div></body></html>")
    return "".join(p)
