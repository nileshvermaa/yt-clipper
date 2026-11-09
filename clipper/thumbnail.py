"""Custom 1280x720 thumbnail: pick the sharpest, most colourful frame, add bold headline text (CPU, ~1 s)."""
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

W, H = 1280, 720
IMPACT = r"C:\Windows\Fonts\impact.ttf"  # shortcut: Windows font path, ship a font in fonts/ to run elsewhere


def _score(img):
    """Colourful game footage with a big person or vehicle wins; text cards and screenshots lose."""
    from . import subject
    bright = img.mean()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    flat = (cv2.Laplacian(gray, cv2.CV_64F) == 0).mean()  # share of perfectly flat pixels: UI cards, tweets
    white = (gray > 225).mean()
    if bright < 40 or bright > 210 or white > 0.2 or flat > 0.5:
        return 0
    b, g, r = cv2.split(img.astype("float"))
    rg, yb = np.abs(r - g), np.abs(0.5 * (r + g) - b)
    colour = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    try:
        dets = subject.detect(img)
    except Exception:  # detector unavailable: colour alone still works
        dets = []
    area = max((w * h for _, _, w, h, _, _ in dets), default=0) / (W * H)
    return colour * (1 + 4 * min(area, 0.35))


def top_frames(spans, k=3, per_span=3):
    """spans: [(video_path, start_sec, end_sec)]. Best frame of each span, the k best overall (varied picks)."""
    picks = []
    for path, start, end in spans:
        best, best_s = None, -1
        cap = cv2.VideoCapture(str(path))
        for n in range(per_span):
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * (start + (end - start) * (n + 1) / (per_span + 1)))
            ok, img = cap.read()
            if ok:
                img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
                sc = _score(img)
                if sc > best_s:
                    best, best_s = img, sc
        cap.release()
        if best is not None and best_s > 0:
            picks.append((best_s, best))
    return [img for _, img in sorted(picks, key=lambda p: -p[0])[:k]]


def _text(draw, xy, text, size, fill):
    font = ImageFont.truetype(IMPACT, size)
    draw.text(xy, text, font=font, fill=fill, stroke_width=max(4, size // 14), stroke_fill="black")
    return draw.textbbox(xy, text, font=font, stroke_width=max(4, size // 14))


def make(spans, out, k=3, **text):
    """Write k candidate thumbnails <out stem>.1.jpg ... (best first). Returns their paths."""
    frames = top_frames(spans, k)
    if not frames:
        raise RuntimeError("no usable frame for the thumbnail")
    paths = []
    for n, frame in enumerate(frames, 1):
        p = out.with_name(f"{out.stem}.{n}.jpg")
        compose(frame, p, **text)
        paths.append(str(p))
    return paths


def compose(frame, out, headline="ALL NEW INFO", top="GTA 6", badge="THIS WEEK"):
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.35)).enhance(1.12)
    # dark gradient on the left so the text pops on any frame
    grad = Image.linear_gradient("L").rotate(90).resize((W, H)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    img = Image.composite(Image.new("RGB", (W, H), "black"), img, grad.point(lambda v: int(v * 0.75)))
    d = ImageDraw.Draw(img)
    box = _text(d, (48, 70), top, 150, "white")
    words = headline.split()
    mid = max(1, len(words) // 2)
    y = box[3] + 10
    for line in (" ".join(words[:mid]), " ".join(words[mid:])):
        if line:
            y = _text(d, (48, y), line, 170, "#FFE000")[3] + 4
    bf = ImageFont.truetype(IMPACT, 64)
    bw = d.textlength(badge, font=bf)
    d.rectangle([W - bw - 70, 40, W - 30, 130], fill="#E10600")
    d.text((W - bw - 50, 46), badge, font=bf, fill="white")
    img.save(out, "JPEG", quality=90)  # YouTube limit is 2 MB; this is ~200-400 KB
    return out
