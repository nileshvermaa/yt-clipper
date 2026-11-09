"""Stage 6b: quality gate between render and upload.

Free checks (no API, nearly no CPU): file sanity, silent audio, near-duplicates, then a contact
sheet (6 frames) that Claude looks at before approving. Per-video log in workspace/<id>/log.txt.
"""
import datetime as dt
import re
import subprocess
from pathlib import Path



def log(meta, msg):
    with open(Path(meta["workdir"]) / "log.txt", "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


def sheet(video, out):
    """3x2 grid of evenly spaced frames. Low impact: NVDEC decode, tiny frames, one pass."""
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True).stdout.strip() or 0)
    if dur <= 0:
        return None
    fps = 6 / dur
    cmd = ["ffmpeg", "-y", "-v", "error", "-hwaccel", "auto", "-i", str(video),
           "-vf", f"fps={fps:.5f},scale=360:-2,tile=3x2", "-frames:v", "1", "-q:v", "4", str(out)]
    subprocess.run(cmd, check=False)
    return out if Path(out).exists() else None


def mean_volume(video):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(video), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def _overlap(a, b):
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    return inter / max(1e-6, min(a["end"] - a["start"], b["end"] - b["start"]))


def problems(meta, clips, clip):
    """List of reasons this clip should not go out (empty = fine)."""
    out = []
    f = Path(clip.get("file", ""))
    if not f.exists() or f.stat().st_size < 200_000:
        return ["rendered file missing or tiny"]
    vol = mean_volume(f)
    if vol is not None and vol < -55:
        out.append(f"audio is silent ({vol:.0f} dB)")
    for other in clips:
        if other is clip or other["status"] in ("selected", "rejected", "skipped"):
            continue
        if other["n"] < clip["n"] and _overlap(clip, other) > 0.5:
            out.append(f"overlaps clip #{other['n']} by {_overlap(clip, other):.0%}")
    return out


def prepare_review(meta, clips, save):
    """Rendered clips -> contact sheet + automatic checks. Returns clips now awaiting review."""
    waiting, changed = [], False
    for c in clips:
        if c["status"] != "rendered":
            continue
        bad = problems(meta, clips, c)
        changed = True
        if bad:
            c["status"], c["reason"] = "rejected", "; ".join(bad)
            log(meta, f"clip {c['n']} rejected automatically: {c['reason']}")
            continue
        png = Path(c["file"]).with_suffix(".sheet.jpg")
        sheet(c["file"], png)
        c["status"], c["sheet"] = "review", str(png)
        log(meta, f"clip {c['n']} ready for review: {png.name}")
        waiting.append(c)
    if changed:  # never write clips.json for a video that has no clips yet (it would block apply_picks)
        save(meta, clips)
    return waiting
