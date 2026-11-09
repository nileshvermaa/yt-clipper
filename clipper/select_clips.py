"""Stage 3: heatmap pre-filter (free) + one small Claude call to pick clips.

Token budget: only transcript lines near the top heatmap peaks are sent, as compact
"[line|seconds] text" rows. Claude answers with line numbers; Python converts them to
exact word timestamps, so the model never handles fine-grained timing.
"""
import json
from pathlib import Path

import anthropic

from . import config, signals

TOOL = {
    "name": "emit_clips",
    "description": "Return the best standalone short-form clips.",
    "input_schema": {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                        "title": {"type": "string", "description": "3-7 words, under 45 chars, one CAPS word, ends with ... or !?"},
                        "description": {"type": "string", "description": "1-2 sentences of context"},
                        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                        "score": {"type": "integer", "description": "1-10 virality estimate"},
                    },
                    "required": ["start_line", "end_line", "title", "description", "tags", "score"],
                },
            }
        },
        "required": ["clips"],
    },
}

SYSTEM = (
    "You pick moments from a video transcript to post as YouTube Shorts. Each clip must: "
    "open with a strong hook in the first sentence, be understandable without the rest of the video, "
    "end on a punchline or completed thought, and span {lo:.0f}-{hi:.0f} seconds "
    "(use the [line|seconds] stamps). Lines come from separate windows marked '---'; never span a '---'. "
    "Prefer funny, surprising, emotional or controversial moments. Return exactly {n} clips, best first, "
    "non-overlapping. Write titles in the transcript's language. "
    "Title style (proven on top GTA 6 Shorts): 3-7 words, under 45 chars, start with 'GTA 6' or put it early, "
    "one key word in CAPS, end with '...' or '!?'. Strong patterns: 'Do NOT ...', 'GTA 6 has a BIG Problem...', "
    "'GTA 6's MAP is how LONG!?', 'Hidden Details in ...', 'Why GTA 6 has NO ...'. Must be true to the clip; "
    "no emoji, no hashtags."
)


def _peak_windows(meta, segments=None):
    """Windows worth reading: top moments by the free multi-signal score (heat + loudness + speech + activity),
    falling back to the heatmap alone, then to the start of the video."""
    if segments is not None:
        try:
            wins = signals.top_windows(meta, segments)
            if wins:
                return wins
        except Exception as e:  # scoring must never block clipping
            print(f"  moment scoring unavailable ({str(e)[:80]}); using heatmap only")
    hm = meta.get("heatmap") or []
    dur = meta.get("duration") or 0
    if not hm:
        return [(0, min(dur or 1e9, config.NO_HEATMAP_MAX_MIN * 60))]
    # skip the first 20s (intro spike is almost always just video start)
    pts = sorted((p for p in hm if p["start_time"] > 20), key=lambda p: p["value"], reverse=True)
    wins = []
    for p in pts[: config.HEATMAP_PEAKS]:
        mid = (p["start_time"] + p["end_time"]) / 2
        wins.append((max(0, mid - config.PEAK_CONTEXT_SEC), mid + config.PEAK_CONTEXT_SEC))
    wins.sort()
    merged = [list(wins[0])]
    for a, b in wins[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(w) for w in merged]


def _build_prompt(segments, windows):
    rows, index = [], []  # index[i] = segment idx for line i
    for w in windows:
        a, b = w[0], w[1]
        label = w[2] if len(w) > 2 else ""
        chunk = [i for i, s in enumerate(segments) if s["end"] > a and s["start"] < b]
        if not chunk:
            continue
        if rows:
            rows.append(f"--- next window ({label})" if label else "---")
        for i in chunk:
            rows.append(f"[{len(index)}|{int(segments[i]['start'])}] {segments[i]['text']}")
            index.append(i)
    return "\n".join(rows), index


def _snap(segments, i0, i1):
    """Expand/trim to the duration envelope using whole segments, return (start, end)."""
    i0, i1 = max(0, i0), min(len(segments) - 1, max(i0, i1))
    while segments[i1]["end"] - segments[i0]["start"] < config.MIN_CLIP_SEC and i1 + 1 < len(segments):
        i1 += 1
    while segments[i1]["end"] - segments[i0]["start"] > config.MAX_CLIP_SEC and i1 > i0:
        i1 -= 1
    # small padding so the first/last word isn't clipped
    start = max(0.0, segments[i0]["words"][0]["start"] - 0.15)
    end = segments[i1]["words"][-1]["end"] + 0.35
    return round(start, 2), round(end, 2)


def prepare(meta, segments):
    """No-API mode: write candidates.txt for Claude (in the app) to read and answer with picks.json."""
    work = Path(meta["workdir"])
    body, index = _build_prompt(segments, _peak_windows(meta, segments))
    if not index:
        raise RuntimeError("Transcript is empty; nothing to clip.")
    rules = SYSTEM.format(lo=config.MIN_CLIP_SEC, hi=config.MAX_CLIP_SEC, n=config.CLIPS_PER_VIDEO)
    (work / "candidates.txt").write_text(
        f"{rules}\n\nAnswer by writing picks.json in this folder: "
        '{"clips": [{"start_line", "end_line", "title", "description", "tags", "score"}]}\n\n'
        f"VIDEO: {meta['title']}\n\n{body}\n",
        encoding="utf-8",
    )
    (work / "lines.json").write_text(json.dumps(index), encoding="utf-8")
    return work / "candidates.txt"


def apply_picks(meta, segments):
    """No-API mode: turn picks.json (written by Claude) into clips.json."""
    work = Path(meta["workdir"])
    out = work / "clips.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    raw = json.loads((work / "picks.json").read_text(encoding="utf-8"))
    raw = raw["clips"] if isinstance(raw, dict) else raw
    index = json.loads((work / "lines.json").read_text(encoding="utf-8"))
    return _finalize(meta, segments, raw, index, out)


def select(meta, segments):
    out = Path(meta["workdir"]) / "clips.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))

    windows = _peak_windows(meta, segments)
    body, index = _build_prompt(segments, windows)
    if not index:
        raise RuntimeError("Transcript is empty; nothing to clip.")
    print(f"  sending {len(index)} lines (~{len(body)//4} tokens) to {config.ANTHROPIC_MODEL}")

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1500,
        system=SYSTEM.format(lo=config.MIN_CLIP_SEC, hi=config.MAX_CLIP_SEC, n=config.CLIPS_PER_VIDEO),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "emit_clips"},
        messages=[{"role": "user", "content": f"VIDEO: {meta['title']}\n\n{body}"}],
    )
    u = resp.usage
    print(f"  tokens: in={u.input_tokens} out={u.output_tokens}")
    raw = next(b.input for b in resp.content if b.type == "tool_use")["clips"]
    return _finalize(meta, segments, raw, index, out)


def _finalize(meta, segments, raw, index, out):
    """Validate line numbers, snap to word timings, drop overlaps, save clips.json."""
    clips, used = [], []
    for c in raw:
        a, b = sorted((c["start_line"], c["end_line"]))
        if not (0 <= a < len(index)):
            continue  # hallucinated line number
        b = min(b, len(index) - 1)
        start, end = _snap(segments, index[a], index[b])
        if any(start < ue and end > us for us, ue in used):
            continue  # overlap
        if meta.get("duration") and end > meta["duration"]:
            end = float(meta["duration"])
        if end - start < 10:
            continue
        used.append((start, end))
        clips.append({
            "n": len(clips) + 1, "start": start, "end": end,
            "title": c["title"][:90], "description": c["description"],
            "tags": c.get("tags", []), "score": c.get("score", 5), "status": "selected",
        })
    out.write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")
    return clips
