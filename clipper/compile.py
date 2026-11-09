"""Weekly long-form (16:9) compilation from approved/uploaded clips, cut from the local 1080p copies."""
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

from . import config, render, review

OUT = config.WORKSPACE / "compilations"
FONT = r"C\:/Windows/Fonts/arialbd.ttf"  # shortcut: Windows-only font path, swap for fonts/ if run elsewhere
TARGET_SEC, MIN_SEC = 600, 180


def _pick(days):
    """Best approved/uploaded clips rendered in the last `days` days, not used in an earlier compilation."""
    used = set()
    for j in OUT.glob("*.json"):
        used |= set(json.loads(j.read_text(encoding="utf-8"))["used"])
    cutoff = time.time() - days * 86400
    cands = []
    for meta_file in config.WORKSPACE.glob("*/meta.json"):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        cf = meta_file.parent / "clips.json"
        if not cf.exists():
            continue
        for c in json.loads(cf.read_text(encoding="utf-8")):
            f = Path(c.get("file", ""))
            key = f"{meta['id']}#{c['n']}"
            if c["status"] in ("approved", "uploaded") and f.exists() and f.stat().st_mtime >= cutoff and key not in used:
                cands.append((c.get("score", 5), key, meta, c))
    cands.sort(key=lambda x: -x[0])
    chosen, total = [], 0
    for _, key, meta, c in cands:
        if total >= TARGET_SEC:
            break
        if sum(1 for _, m, _ in chosen if m["id"] == meta["id"]) >= 2:
            continue  # max 2 segments per source video, keeps it varied
        chosen.append((key, meta, c))
        total += c["end"] - c["start"]
    return chosen, total


W, H = 2560, 1440  # 1440p upload gets YouTube's high-bitrate VP9/AV1 encode, so it stays sharp even when watched at 1080p


def _segment(meta, c, out, txt):
    """One segment: NVDEC decode -> CUDA Lanczos scale -> NVENC. CPU only draws the credit bar."""
    from . import download
    txt.write_text(f"{c['title']}   |   Credit: {meta['channel']}", encoding="utf-8")
    tf = str(txt).replace("\\", "/").replace(":", r"\:")
    bar = (f"drawtext=textfile='{tf}':fontfile='{FONT}':x=54:y=54:fontsize=46:fontcolor=white"
           ":box=1:boxcolor=black@0.55:boxborderw=18")
    seek = ["-ss", f"{c['start']:.2f}", "-to", f"{c['end']:.2f}"]
    s = download.stream_inputs(meta, "vp09")
    if s and s["height"] > 1080:  # sharper than the 1080p file on disk; ffmpeg only fetches these seconds
        net = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1"]
        ins = net + ["-headers", s["v_hdr"]] + seek + ["-i", s["v"]] + net + ["-headers", s["a_hdr"]] + seek + ["-i", s["a"]]
        maps = ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        ins, maps = seek + ["-i", meta["source"]], ["-map", "0:v:0", "-map", "0:a:0"]
    if render._has_nvenc():
        hw = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        vf = (f"scale_cuda={W}:{H}:interp_algo=lanczos:force_original_aspect_ratio=decrease,hwdownload,format=nv12,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,{bar}")
        venc = ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
                "-maxrate", "40M", "-bufsize", "80M", "-profile:v", "high"]
    else:
        hw = []
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,{bar}"
        venc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]
    def run(ins, maps):
        subprocess.run(["ffmpeg", "-y", "-v", "error", *hw, *ins, *maps, "-vf", vf, *venc, "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5",
                        "-threads", str(config.CPU_THREADS), str(out)], check=True)
    try:
        run(ins, maps)
    except subprocess.CalledProcessError:
        if "-headers" not in ins:
            raise
        print(f"  hi-res stream failed for '{c['title']}'; using the 1080p file on disk")
        run(seek + ["-i", meta["source"]], ["-map", "0:v:0", "-map", "0:a:0"])


def _ts(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def build(days=7):
    chosen, total = _pick(days)
    if total < MIN_SEC:
        raise SystemExit(f"only {total:.0f}s of fresh approved clips; need {MIN_SEC}s")
    name = dt.date.today().isoformat()
    work = OUT / name
    work.mkdir(parents=True, exist_ok=True)
    parts, chapters, t = [], [], 0.0
    for i, (key, meta, c) in enumerate(chosen):
        seg = work / f"{i:02d}.mp4"
        _segment(meta, c, seg, work / f"{i:02d}.txt")
        parts.append(seg)
        chapters.append(f"{_ts(t)} {c['title']} (credit: {meta['channel']} {meta['url']})")
        t += c["end"] - c["start"]
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    final = OUT / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-c", "copy", "-movflags", "+faststart", str(final.resolve())], check=True, cwd=work)
    got = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(final)], capture_output=True, text=True).stdout or 0)
    if got < t - 5:
        raise RuntimeError(f"compilation is {got:.0f}s, segments add up to {t:.0f}s")
    review.sheet(final, OUT / f"{name}.sheet.jpg")
    info = {"file": str(final), "status": "review", "used": [k for k, _, _ in chosen],
            "title": f"GTA 6 - ALL New Info This Week ({dt.date.today():%b. %d})",
            "description": "The biggest GTA 6 news, leaks and details from this week, from the creators below.\n\n"
                           "Chapters:\n" + "\n".join(chapters),
            "tags": ["GTA 6", "GTA VI", "GTA 6 news", "GTA 6 this week", "Rockstar", "Vice City"]}
    (OUT / f"{name}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return OUT / f"{name}.json", info, t


def upload_ready():
    """Upload compilations marked approved (edit status in the .json, or `compile --approve`)."""
    from . import upload
    for j in sorted(OUT.glob("*.json")):
        info = json.loads(j.read_text(encoding="utf-8"))
        if info["status"] != "approved":
            continue
        meta = {"url": "", "channel": "various creators (see chapters)", "channel_url": ""}
        info["youtube_id"] = upload.upload(info["file"], meta, info, shorts=False)
        info["status"] = "uploaded"
        j.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  uploaded https://youtube.com/watch?v={info['youtube_id']}")
