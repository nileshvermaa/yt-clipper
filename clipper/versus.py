"""'Versus' Shorts: two videos back to back, each framed full-screen 9:16 with a label on top.

e.g. a GTA V chase followed by the matching GTA 6 chase. Each half is tracked/cropped/sharpened the
same way as a normal clip, labelled (and optionally given a logo PNG), then the halves are joined
without re-encoding. No transcript or Claude call is needed.
"""
import re
import shutil
import subprocess
from pathlib import Path

from . import captions, config, download, render

ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Label,{font},120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9,4,8,60,60,110,1
Style: Credit,{font},40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,3,2,0,2,60,60,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _write_ass(path, label, credit, dur, show_label):
    ev = []
    if show_label:
        ev.append(f"Dialogue: 1,{captions._ts(0)},{captions._ts(dur)},Label,,0,0,0,,{captions._esc(label)}")
    if credit:
        ev.append(f"Dialogue: 1,{captions._ts(0)},{captions._ts(dur)},Credit,,0,0,0,,{captions._esc(credit)}")
    Path(path).write_text(ASS.format(font=config.CAPTION_FONT) + "\n".join(ev) + "\n", encoding="utf-8")


def _overlay_logo(part, logo, cdir):
    """Optional: stamp a logo PNG (top centre) over the rendered part. Fast GPU re-encode."""
    out = cdir / "logo.mp4"
    nv = config.USE_GPU_ENCODE and render._has_nvenc()
    enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20", "-b:v", "0"] if nv else ["-c:v", "libx264", "-crf", config.CRF]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(part), "-i", str(logo),
           "-filter_complex", "[1]scale=640:-1[l];[0][l]overlay=(W-w)/2:90:format=auto,format=yuv420p",
           *enc, "-c:a", "copy", str(out)]
    subprocess.run(cmd, check=True)
    shutil.move(out, part)


def _part(url, start, end, label, show_label, logo, cdir, out_fps):
    meta = download.fetch(url)
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "short.mp4").unlink(missing_ok=True)
    _write_ass(cdir / "subs.ass", label, f"Footage: {meta['channel']}", end - start, show_label and not logo)
    part = render.render_segment(meta, cdir, start, end, tag=label, out_fps=out_fps)
    if logo:
        _overlay_logo(part, logo, cdir)
    return meta, part


def build(url_a, a_start, a_end, url_b, b_start, b_end, label_a="GTA V", label_b="GTA VI",
          logo_a=None, logo_b=None, name=None):
    """Render both halves and join them. Returns (final_mp4, meta_a, meta_b)."""
    slug = name or re.sub(r"[^\w]+", "_", f"{label_a}_vs_{label_b}").strip("_").lower()
    root = config.WORKSPACE / "versus" / slug
    root.mkdir(parents=True, exist_ok=True)

    ma, mb = download.fetch(url_a), download.fetch(url_b)
    # both halves must share one frame rate so they can be joined without re-encoding
    fps = min(60, round(max(render.source_fps(ma), render.source_fps(mb)))) if config.OUT_FPS == "auto" else int(config.OUT_FPS)

    ma, pa = _part(url_a, a_start, a_end, label_a, True, logo_a, root / "a", fps)
    mb, pb = _part(url_b, b_start, b_end, label_b, True, logo_b, root / "b", fps)

    lst = root / "list.txt"
    lst.write_text(f"file '{pa.resolve().as_posix()}'\nfile '{pb.resolve().as_posix()}'\n", encoding="utf-8")
    final = root / "versus.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    return final, ma, mb
