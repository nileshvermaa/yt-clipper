"""Narrated explainer video in the channel's own style, from a script Claude writes (no API key).

script.json: {"title", "thumb": {"top", "headline", "badge"}, "description", "tags",
              "sections": [{"heading", "text", "broll": [[video_id, start_sec, end_sec], ...]}]}
Each section = Kokoro voiceover + B-roll cut from the local copies (5 s shots, text cards skipped).
Branding is overlaid in the same ffmpeg pass: title card on the first 3.5 s, sliding section headings,
channel bug, footage credit and a subscribe card at the end. NVDEC/NVENC do the heavy lifting.
"""
import json
import re
import subprocess
import wave
from pathlib import Path

import cv2
import numpy as np

from . import compile as comp, config, thumbnail, transcribe

OUT = config.WORKSPACE / "explainers"
W, H = comp.W, comp.H
IMPACT = r"C\:/Windows/Fonts/impact.ttf"  # shortcut: Windows font paths, ship fonts/ to run elsewhere
ARIAL = r"C\:/Windows/Fonts/arialbd.ttf"
YELLOW, RED = "0xFFE000", "0xE10600"
SHOT = 5.0  # seconds per B-roll cut; quick cuts keep commentary videos moving
VOICE = "am_michael"  # Kokoro voice; same voice every video = consistent channel sound


def _channel_name():
    cache = config.WORKSPACE / "channel.json"
    if not cache.exists():
        from . import upload
        snip = upload._service().channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]
        cache.write_text(json.dumps({"title": snip["title"]}), encoding="utf-8")
    return json.loads(cache.read_text(encoding="utf-8"))["title"]


_KOKORO = []


def _tts(text, out):
    transcribe._add_cuda_dlls()
    from kokoro_onnx import Kokoro
    if not _KOKORO:  # load the 325 MB model once per run, not once per section
        _KOKORO.append(Kokoro(str(config.ROOT / "models/tts/kokoro-v1.0.onnx"),
                              str(config.ROOT / "models/tts/voices-v1.0.bin")))
    k = _KOKORO[0]
    # one sentence per call: long passages overflow Kokoro's context and come out garbled
    chunks, sr = [], 24000
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        samples, sr = k.create(sentence, voice=VOICE, speed=1.05, lang="en-us")
        chunks += [samples, np.zeros(int(sr * 0.18))]
    pcm = np.concatenate(chunks + [np.zeros(int(sr * 0.35))])  # breath between sections
    rate = len(text.split()) / (len(pcm) / sr)
    # shortcut: speaking-rate check only (normal is 2.4-3.4 words/s); a Whisper read-back would catch more
    if not 1.8 <= rate <= 4.2:
        raise RuntimeError(f"voice-over looks garbled ({rate:.1f} words/s) for: {text[:60]}...")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return len(pcm) / sr


def _shots(broll, need):
    """5 s windows from hi-res copies of the given ranges, skipping text cards/faces, cycled to `need` s."""
    from . import download
    good = []
    for vid, start, end in broll:
        try:
            src, t, stop = download.fetch_range(vid, start, end), 0.0, None
        except Exception as e:  # network/bot check: the low-bitrate local copy still makes a video
            print(f"  hi-res B-roll failed for {vid} ({str(e)[:60]}); using the local copy")
            src, t, stop = config.WORKSPACE / vid / "source.mp4", float(start), float(end)
        cap = cv2.VideoCapture(str(src))
        if stop is None:
            stop = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
        while t + SHOT <= stop:
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * (t + SHOT / 2))
            ok, img = cap.read()
            if ok and thumbnail._score(cv2.resize(img, (thumbnail.W, thumbnail.H))) > 0:
                good.append((src, t))
            t += SHOT
        cap.release()
    if not good:
        raise RuntimeError(f"no usable B-roll in {broll}")
    shots, i = [], 0
    while len(shots) * SHOT < need + SHOT:
        shots.append(good[i % len(good)])
        i += 1
    return shots


def _esc(path):
    return str(path).replace("\\", "/").replace(":", r"\:")


def _section(n, sec, total, work, brand, intro_title):
    wav = work / f"{n:02d}.wav"
    dur = _tts(sec["text"], wav)
    shots = _shots(sec["broll"], dur)
    lst = work / f"{n:02d}.txt"
    lst.write_text("".join(f"file '{Path(s).as_posix()}'\ninpoint {t:.2f}\noutpoint {t + SHOT:.2f}\n" for s, t in shots),
                   encoding="utf-8")
    texts = {"head": sec["heading"].upper(), "brand": brand.upper(),
             "credit": "Footage: " + ", ".join(sorted({json.loads((config.WORKSPACE / v / "meta.json").read_text(
                 encoding="utf-8"))["channel"] for v, _, _ in sec["broll"]}))}
    if intro_title:
        texts["title"] = intro_title.upper()
    if n == total:
        texts["sub"] = "SUBSCRIBE FOR DAILY GTA 6 NEWS"
    for k, v in texts.items():
        (work / f"{n:02d}.{k}.txt").write_text(v, encoding="utf-8")
    tf = lambda k: f"textfile='{_esc(work / f'{n:02d}.{k}.txt')}'"  # noqa: E731
    h0 = 3.8 if intro_title else 0.2  # heading slides in after the title card
    slide = f"if(lt(t-{h0},0.35),-tw+(tw+110)*(t-{h0})/0.35,110)"
    f = [f"drawbox=x=0:y=ih-300:w=26:h=130:color={RED}:t=fill:enable='between(t,{h0},{h0 + 5})'",
         f"drawtext={tf('head')}:fontfile='{IMPACT}':fontsize=96:fontcolor={YELLOW}:x='{slide}':y=h-292"
         f":box=1:boxcolor=black@0.72:boxborderw=22:enable='between(t,{h0},{h0 + 5})'",
         f"drawtext={tf('brand')}:fontfile='{IMPACT}':fontsize=48:fontcolor=white:x=w-tw-60:y=50"
         f":box=1:boxcolor={RED}@0.9:boxborderw=14",
         f"drawtext={tf('credit')}:fontfile='{ARIAL}':fontsize=30:fontcolor=white@0.85:x=w-tw-50:y=h-70"
         f":box=1:boxcolor=black@0.5:boxborderw=10"]
    if intro_title:
        a = "min(1,t/0.4)"
        f += ["drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill:enable='lt(t,3.6)'",
              f"drawtext=text='GTA 6':fontfile='{IMPACT}':fontsize=210:fontcolor=white:alpha='{a}'"
              f":borderw=10:bordercolor=black:x=(w-tw)/2:y='h/2-330+40*(1-{a})':enable='lt(t,3.6)'",
              f"drawtext={tf('title')}:fontfile='{IMPACT}':fontsize=120:fontcolor={YELLOW}:alpha='{a}'"
              f":borderw=8:bordercolor=black:x=(w-tw)/2:y='h/2-60+40*(1-{a})':enable='lt(t,3.6)'"]
    if n == total:
        s0 = max(0.0, dur - 4)
        a = f"min(1,(t-{s0})/0.4)"
        f += [f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill:enable='gt(t,{s0})'",
              f"drawbox=x=(iw-1500)/2:y=ih/2-110:w=1500:h=220:color={RED}:t=fill:enable='gt(t,{s0})'",
              f"drawtext={tf('sub')}:fontfile='{IMPACT}':fontsize=110:fontcolor=white:alpha='{a}'"
              f":x=(w-tw)/2:y=(h-th)/2:enable='gt(t,{s0})'"]
    vf = (f"scale_cuda={W}:{H}:interp_algo=lanczos:force_original_aspect_ratio=decrease,hwdownload,format=nv12,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p," + ",".join(f))
    out = work / f"{n:02d}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                    "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
                    "-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-t", f"{dur:.2f}",
                    "-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
                    "-maxrate", "40M", "-bufsize", "80M", "-pix_fmt", "yuv420p",
                    "-af", "loudnorm=I=-14:TP=-1.5,aresample=48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
                    "-threads", str(config.CPU_THREADS), str(out)], check=True)
    return out, dur


def validate(s):
    """Problems in a script, as plain sentences the script writer can act on (empty list = good)."""
    bad = []
    secs = s.get("sections") or []
    if not 5 <= len(secs) <= 9:
        bad.append(f"{len(secs)} sections; use 5-9")
    words = sum(len(sec.get("text", "").split()) for sec in secs)
    if not 450 <= words <= 900:
        bad.append(f"{words} words of narration; use 450-900 (about 3-6 minutes)")
    if not 5 <= len(s.get("title", "")) <= 60:
        bad.append("title must be 5-60 characters")
    for n, sec in enumerate(secs, 1):
        if not 3 <= len(sec.get("heading", "")) <= 40:
            bad.append(f"section {n}: heading must be 3-40 characters")
        if len(sec.get("text", "").split()) < 25:
            bad.append(f"section {n}: narration under 25 words")
        if re.search(r"\d", sec.get("text", "")):
            bad.append(f"section {n}: spell numbers as words in the narration (the voice reads digits badly)")
        if not sec.get("broll"):
            bad.append(f"section {n}: no broll")
        for item in sec.get("broll", []):
            if len(item) != 3:
                bad.append(f"section {n}: broll entries are [video_id, start_sec, end_sec]")
                continue
            vid, a, b = item
            if not (config.WORKSPACE / str(vid) / "source.mp4").exists():
                bad.append(f"section {n}: video {vid} is not prepared (run: python -m clipper prepare <url>)")
            elif b - a < 30:
                bad.append(f"section {n}: broll range {a}-{b} is under 30 seconds")
    return bad


def build(script_path):
    script_path = Path(script_path)
    s = json.loads(script_path.read_text(encoding="utf-8"))
    bad = validate(s)
    if bad:
        raise SystemExit("script problems:\n  - " + "\n  - ".join(bad))
    work = OUT / script_path.stem
    work.mkdir(parents=True, exist_ok=True)
    brand = _channel_name()
    parts, chapters, t = [], [], 0.0
    for n, sec in enumerate(s["sections"], 1):
        print(f"  [{n}/{len(s['sections'])}] {sec['heading']}")
        out, dur = _section(n, sec, len(s["sections"]), work, brand, s["title"] if n == 1 else None)
        parts.append(out)
        chapters.append(f"{comp._ts(t)} {sec['heading']}")
        t += dur
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    final = work / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy",
                    "-movflags", "+faststart", str(final.resolve())], check=True, cwd=work)
    from . import review
    got = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(final)], capture_output=True, text=True).stdout or 0)
    if abs(got - t) > 3:
        raise RuntimeError(f"final video is {got:.0f}s but the narration is {t:.0f}s")
    review.sheet(final, work / "final.sheet.jpg")
    vids = sorted({v for sec in s["sections"] for v, _, _ in sec["broll"]} | set(s.get("sources", [])))
    metas = [json.loads((config.WORKSPACE / v / "meta.json").read_text(encoding="utf-8")) for v in vids]
    spans = [(config.WORKSPACE / v / "source.mp4", a, b) for sec in s["sections"] for v, a, b in sec["broll"]][:8]
    thumbs = thumbnail.make(spans, work / "thumb.jpg", **s.get("thumb", {}))
    info = {"file": str(final), "thumbs": thumbs, "thumb": thumbs[0], "status": "review", "title": s["title"],
            "tags": s.get("tags", []),
            "description": s.get("description", "") + "\n\nChapters:\n" + "\n".join(chapters)
            + "\n\nFootage and reporting credit:\n" + "\n".join(f"{m['channel']}: {m['url']}" for m in metas)}
    (work / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return work, info, t


def upload_it(script_path, pick=1):
    from . import upload
    work = OUT / Path(script_path).stem
    info = json.loads((work / "info.json").read_text(encoding="utf-8"))
    info["thumb"] = info["thumbs"][min(pick, len(info["thumbs"])) - 1]
    meta = {"url": "", "channel": "", "channel_url": ""}
    info["youtube_id"] = upload.upload(info["file"], meta, info, shorts=False)
    info["status"] = "uploaded"
    info["thumb_set"] = upload.set_thumbnail(info["youtube_id"], info["thumb"])
    (work / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info
