"""Stage 2: local word-level transcription with faster-whisper (no API cost)."""
import json
from pathlib import Path

from . import config


def _add_cuda_dlls():
    """Expose pip-installed CUDA libs (nvidia-cublas/cudnn wheels) to ctranslate2 on Windows."""
    import os
    import site
    for sp in site.getsitepackages():
        for d in sorted((Path(sp) / "nvidia").glob("*/bin")):
            os.add_dll_directory(str(d))
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"


def _from_youtube_captions(path):
    """Parse a YouTube json3 caption file into word-timed segments (no GPU needed)."""
    events = json.loads(path.read_text(encoding="utf-8")).get("events", [])
    words = []
    for ev in events:
        segs = ev.get("segs")
        if not segs or "tStartMs" not in ev:
            continue
        t0 = ev["tStartMs"] / 1000
        dur = ev.get("dDurationMs", 0) / 1000
        toks = [(s.get("tOffsetMs"), w) for s in segs for w in [s.get("utf8", "").strip()] if w and w != "\n"]
        if not toks:
            continue
        if all(o is None for o, _ in toks[1:]) and len(toks) == 1 and " " in toks[0][1]:
            # manual captions: one line of text, no per-word timing -> spread evenly
            parts = toks[0][1].split()
            step = (dur or len(parts) * 0.3) / len(parts)
            toks = [(i * step * 1000, p) for i, p in enumerate(parts)]
        for o, w in toks:
            for i, part in enumerate(w.split()):
                words.append({"start": round(t0 + (o or 0) / 1000 + i * 0.05, 2), "word": part, "_ev_end": t0 + dur})
    if not words:
        return []
    words.sort(key=lambda w: w["start"])
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else w["_ev_end"]
        w["end"] = round(min(max(nxt, w["start"] + 0.1), w["start"] + 1.5), 2)
        del w["_ev_end"]

    # group words into sentence-like segments: break on punctuation, pauses or length
    segments, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 9
        if w["word"][-1:] in ".?!" or gap > 0.7 or len(cur) >= 14:
            segments.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                             "text": " ".join(x["word"] for x in cur), "words": cur})
            cur = []
    return segments


def caption_problem(segs):
    """None if the captions look like real speech, else a short reason.

    Auto-captions in the wrong language come out as loops of a few tokens ('Taco Taco another Taco').
    Calibrated on real videos: good captions stay under 2.5% for the most common content word, 1.5%
    consecutive repeats and a worst stretch of vocabulary variety above 0.47; the garbled one hit
    13%, 9.6% and 0.23.
    """
    import re
    from collections import Counter
    words = [re.sub(r"[^\w']", "", w["word"].lower()) for s in segs for w in s["words"]]
    words = [w for w in words if w]
    if len(words) < 60:
        return None  # too little speech to judge (music/gameplay with no talking is fine)
    ttr = [len(set(words[i:i + 40])) / 40 for i in range(0, len(words) - 40, 20)]
    stop = set("the a an and or of to in is it that this i you we he she they on for with as at be are was".split())
    common = Counter(w for w in words if w not in stop).most_common(1)
    top = common[0][1] / len(words) if common else 0
    runs = sum(1 for a, b in zip(words, words[1:]) if a == b) / len(words)
    if top > 0.06:
        return f"one word makes up {top:.0%} of the text"
    if runs > 0.04:
        return f"{runs:.0%} of words are immediate repeats"
    if ttr and min(ttr) < 0.3:
        return "stretches of near-identical words"
    return None


def transcribe(meta):
    """Return list of segments: {start, end, text, words:[{start,end,word}]}. Cached on disk."""
    out = Path(meta["workdir"]) / "transcript.json"
    work = Path(meta["workdir"])
    if out.exists():
        cached = json.loads(out.read_text(encoding="utf-8"))
        if (work / "language.txt").exists() or not caption_problem(cached):
            return cached
        print("  cached transcript fails the quality check; redoing it")  # saved before the check existed
        out.unlink()

    caps = sorted(work.glob("captions*.json3"), key=lambda p: "orig" not in p.name)
    if caps:
        result = _from_youtube_captions(caps[0])
        if result:
            bad = caption_problem(result)
            if bad:
                print(f"  YouTube captions look unreliable ({bad}); transcribing with Whisper instead")
            else:
                print(f"  using YouTube captions ({caps[0].name}, {len(result)} segments) - no GPU")
                out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                lang = caps[0].name.split(".")[1].split("-")[0] if caps[0].name.count(".") >= 2 else "en"
                (work / "language.txt").write_text(lang, encoding="utf-8")
                return result

    _add_cuda_dlls()
    from faster_whisper import WhisperModel

    device = config.WHISPER_DEVICE
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"
    print(f"  whisper {config.WHISPER_MODEL} on {device} ({compute})")

    model = WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute,
                         cpu_threads=config.CPU_THREADS, num_workers=1)
    segments, info = model.transcribe(
        meta["source"],
        language=config.WHISPER_LANGUAGE,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
    )
    (work / "language.txt").write_text(info.language, encoding="utf-8")
    print(f"  spoken language: {info.language} ({info.language_probability:.0%})")
    if (config.WHISPER_LANGUAGE is None and info.language != config.CHANNEL_LANGUAGE
            and info.language_probability > 0.6):
        # wrong language for this channel: don't spend GPU time transcribing the whole video
        print(f"  not '{config.CHANNEL_LANGUAGE}': skipping the transcription")
        out.write_text("[]", encoding="utf-8")
        return []
    result = []
    for s in segments:
        words = [
            {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
            for w in (s.words or []) if w.word.strip()
        ]
        if words:
            result.append({"start": round(s.start, 2), "end": round(s.end, 2),
                           "text": s.text.strip(), "words": words})
    out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
