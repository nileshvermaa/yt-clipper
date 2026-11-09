"""Stage 5: word-by-word karaoke captions as an .ass subtitle file (rendered by libass)."""
from . import config

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},92,&H0000E5FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,560,1
Style: Credit,{font},44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,3,2,0,8,60,60,110,1
Style: Hook,{font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,0,0,3,14,0,8,80,80,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _esc(s):
    return s.replace("{", "(").replace("}", ")").replace("\n", " ")


def build(segments, clip, channel, path, cap_y=None):
    """cap_y: put the captions' centre at this y (used by the stacked 'reaction' layout)."""
    s0, s1 = clip["start"], clip["end"]
    words = [w for seg in segments for w in seg["words"] if w["end"] > s0 and w["start"] < s1]
    lines = []
    n = config.CAPTION_WORDS_PER_LINE
    for i in range(0, len(words), n):
        chunk = words[i:i + n]
        a = chunk[0]["start"] - s0
        b = (words[i + n]["start"] if i + n < len(words) else chunk[-1]["end"]) - s0
        b = min(b, chunk[-1]["end"] - s0 + 0.6)
        kara = ""
        for j, w in enumerate(chunk):
            nxt = chunk[j + 1]["start"] if j + 1 < len(chunk) else w["end"]
            cs = max(1, round((nxt - w["start"]) * 100))
            kara += f"{{\\k{cs}}}{_esc(w['word']).upper()} "
        pos = f"\\an5\\pos(540,{cap_y})" if cap_y else ""
        lines.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\fad(40,0)}}{kara.strip()}")

    dur = s1 - s0
    if channel and config.CREDIT_TEXT:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(dur)},Credit,,0,0,0,,{_esc(config.CREDIT_TEXT.format(channel=channel))}")
    # title card for the first 3s – the "added value" + hook
    lines.append(f"Dialogue: 1,{_ts(0)},{_ts(min(3.0, dur))},Hook,,0,0,0,,{{\\fad(0,250)}}{_esc(clip['title'])}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER.format(font=config.CAPTION_FONT) + "\n".join(lines) + "\n")
