"""Free moment scoring: which parts of a video are worth showing Claude?

Every 5-second bin of the video gets a score from cheap signals, no AI and almost no CPU:
  heat    YouTube "Most Replayed" curve (when the video has one)
  loud    loudness spikes vs the local baseline: shouting, explosions, crowd noise
  speech  speaking rate: fast talk = excitement
  scene   on-screen activity (frame-to-frame change on tiny GPU-decoded thumbnails)
The top peaks (plus context around them) become the windows sent to Claude, so Claude reads a few
minutes of transcript instead of the whole video and the picks start from verified high-energy moments.
"""
import json
import subprocess
from pathlib import Path

import numpy as np

from . import config

BIN = 5.0  # seconds per scoring bin


def _audio_loudness(source, duration):
    """Per-second RMS in dB (mono, 8 kHz decode: just enough to see loudness changes)."""
    cmd = ["ffmpeg", "-v", "error", "-threads", "1", "-i", str(source), "-vn", "-ac", "1", "-ar", "8000",
           "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    n = int(len(x) // 8000)
    if n < 10:
        return None
    rms = np.sqrt((x[: n * 8000].reshape(n, 8000) ** 2).mean(1) + 1e-10)
    return 20 * np.log10(rms)  # one value per second


def _scene_activity(source, duration):
    """Per-second mean frame-to-frame change on 64x36 thumbnails (GPU decode + GPU downscale)."""
    sh = 36
    n = 64 * sh
    seek = ["-i", str(source)]
    paths = [
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", *seek,
         "-vf", "fps=1,scale_cuda=64:36:format=nv12,hwdownload,format=nv12"],
        ["-hwaccel", "cuda", *seek, "-vf", "fps=1,scale=64:36"],
    ]
    for args in paths:
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-threads", "1", *args, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        frames = []
        try:
            while len(buf := p.stdout.read(n)) == n:
                frames.append(np.frombuffer(buf, np.uint8).reshape(sh, 64).astype(np.int16))
        finally:
            p.stdout.close()
            p.wait()
        if len(frames) > 10:
            d = [0.0] + [float(np.abs(a - b).mean()) for b, a in zip(frames, frames[1:])]
            return np.array(d)
    return None


def _z(x):
    """Robust z-score, clipped so one huge spike can't dominate."""
    x = np.asarray(x, dtype=float)
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    sd = mad if mad > 1e-6 else (x.std() or 1.0)
    return np.clip((x - med) / sd, -2.0, 5.0)


def _per_bin(per_second, nbins, reduce=np.max):
    out = np.zeros(nbins)
    for i in range(nbins):
        seg = per_second[int(i * BIN): int((i + 1) * BIN)]
        out[i] = reduce(seg) if len(seg) else 0.0
    return out


def compute(meta, segments):
    """Return {'bins': n, 'score': [...], 'parts': {name: [...]}} (cached as signals.json)."""
    out = Path(meta["workdir"]) / "signals.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    dur = float(meta.get("duration") or 0)
    nb = max(1, int(np.ceil(dur / BIN)))
    parts = {}

    hm = meta.get("heatmap") or []
    if hm:
        centers = (np.arange(nb) + 0.5) * BIN
        parts["heat"] = np.interp(centers, [(p["start_time"] + p["end_time"]) / 2 for p in hm], [p["value"] for p in hm])

    src = meta["source"]
    loud = _audio_loudness(src, dur)
    if loud is not None:
        base = np.convolve(loud, np.ones(61) / 61, mode="same")  # ~1 min rolling baseline
        parts["loud"] = _per_bin(loud - base, nb, np.max)

    words = np.zeros(nb)
    for s in segments:
        for w in s["words"]:
            b = int(w["start"] // BIN)
            if 0 <= b < nb:
                words[b] += 1
    if words.sum() > 20:
        parts["speech"] = words / BIN

    if config.SCENE_SIGNAL:
        act = _scene_activity(src, dur)
        if act is not None:
            parts["scene"] = _per_bin(act, nb, np.mean)

    weights = {k: v for k, v in config.SIGNAL_WEIGHTS.items() if k in parts}
    total = sum(weights.values()) or 1.0
    score = sum(weights[k] / total * _z(parts[k]) for k in weights)
    score = np.convolve(score, np.ones(3) / 3, mode="same")  # smooth: a moment, not a single bin
    res = {"bins": nb, "bin": BIN, "score": score.tolist(), "used": sorted(weights),
           "parts": {k: _z(v).tolist() for k, v in parts.items()}}
    out.write_text(json.dumps(res), encoding="utf-8")
    return res


def top_windows(meta, segments, peaks=None, context=None):
    """Return [(start, end, label)] windows around the best-scoring moments, merged if they overlap."""
    peaks = peaks or config.HEATMAP_PEAKS
    context = context or config.PEAK_CONTEXT_SEC
    sig = compute(meta, segments)
    score = np.array(sig["score"])
    if score.size == 0 or not sig["used"]:
        return []
    def merge(wins):
        wins = sorted(wins)
        out = [list(wins[0])]
        for a, b, sc, why in wins[1:]:
            if a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b)
                out[-1][2] = max(out[-1][2], sc)
                out[-1][3] = sorted(set(out[-1][3]) | set(why))
            else:
                out.append([a, b, sc, why])
        return out

    order = np.argsort(score)[::-1]
    wins, centres = [], []
    for b in order:
        t = (b + 0.5) * BIN
        if t < 20 or t > (meta.get("duration") or 1e9) - 10:  # skip the intro spike and the very end
            continue
        if any(abs(t - c) < config.PEAK_MIN_GAP_SEC for c in centres):
            continue
        why = [k for k, v in sig["parts"].items() if k in sig["used"] and v[int(b)] > 1.0]
        trial = merge(wins + [[max(0.0, t - context), t + context, float(score[b]), why]])
        # token budget: stop once the merged windows would exceed it (but always keep a few moments)
        if len(centres) >= 3 and sum(w[1] - w[0] for w in trial) > config.WINDOW_BUDGET_SEC:
            break
        wins = trial
        centres.append(t)
        if len(centres) >= peaks:
            break
    return [(a, b, f"score {sc:.1f}: {'+'.join(why) or 'combined'}") for a, b, sc, why in wins]
