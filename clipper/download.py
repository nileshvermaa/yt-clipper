"""Stage 1: download source video + "Most Replayed" heatmap with yt-dlp."""
import json
import re

import yt_dlp

from . import config


def _base_opts():
    opts = {"quiet": True, "no_warnings": True}
    if config.COOKIES_FILE.exists():
        opts["cookiefile"] = str(config.COOKIES_FILE)
    return opts


def _cached(url):
    """Skip YouTube entirely if this video was already downloaded (fewer requests = fewer bot checks)."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    if m:
        work = config.WORKSPACE / m.group(1)
        if (work / "meta.json").exists() and (work / "source.mp4").exists():
            return json.loads((work / "meta.json").read_text(encoding="utf-8"))
    return None


def fetch(url):
    """Download video into workspace/<id>/ and return its metadata dict."""
    if meta := _cached(url):
        return meta
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    vid = info["id"]
    work = config.WORKSPACE / vid
    work.mkdir(parents=True, exist_ok=True)
    meta_path = work / "meta.json"
    source = work / "source.mp4"

    if not source.exists():
        lang = (info.get("language") or "en").split("-")[0]
        opts = _base_opts() | {
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
            "merge_output_format": "mp4",
            "outtmpl": {"default": str(work / "source.%(ext)s"), "subtitle": str(work / "captions")},
            # YouTube's own captions (word-timed json3) replace local Whisper when available
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitlesformat": "json3",
            "subtitleslangs": [f"{lang}-orig", lang],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError:
            if source.exists():
                pass  # video is fine, only captions failed -> Whisper fallback
            else:
                for k in ("writesubtitles", "writeautomaticsub"):
                    opts[k] = False
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

    meta = {
        "id": vid,
        "url": info.get("webpage_url", url),
        "title": info.get("title", ""),
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_url": info.get("channel_url", ""),
        "duration": info.get("duration") or 0,
        "width": info.get("width") or 1920,
        "height": info.get("height") or 1080,
        "heatmap": info.get("heatmap") or [],  # [{start_time, end_time, value}]
        "source": str(source),
        "workdir": str(work),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


_stream_cache = {}


def stream_inputs(meta, codec="vp09"):
    """Direct best-quality stream URLs (up to config.MAX_SOURCE_HEIGHT) for ffmpeg to read a time range from.

    codec "vp09" (8-bit VP9, decoded by NVDEC) or "av01" (8-bit AV1, decoded by Vulkan so frames never
    leave the GPU). The 1080p file on disk is only for transcript/tracking; the final render crops a 9:16
    window out of the frame, so sourcing it from the 4K stream gives a much sharper Short, and ffmpeg
    only fetches the clip's seconds. Returns None when unavailable so the caller can fall back.
    One yt-dlp lookup per video serves both codecs.
    """
    h = config.MAX_SOURCE_HEIGHT
    if not h:
        return None
    if meta["id"] not in _stream_cache:
        _stream_cache[meta["id"]] = _extract_streams(meta, h)
    return _stream_cache[meta["id"]].get(codec)


def _extract_streams(meta, h):
    res = {}
    try:
        opts = _base_opts() | {"format": f"bv*[height<={h}]+ba/b[height<={h}]"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(meta["url"], download=False)
        formats = info.get("formats") or []
        a = next((f for f in (info.get("requested_formats") or [])
                  if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")), None)
        hdr = lambda f: "".join(f"{k}: {x}\r\n" for k, x in f["http_headers"].items())

        def best(ok):
            c = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("height")
                 and f["height"] <= h and f.get("url") and ok(f["vcodec"])]
            return max(c, key=lambda f: (f["height"], f.get("fps") or 0, f.get("tbr") or 0), default=None)

        # 8-bit SDR only: vp09.00 / av01 "...08" (the 10-bit HDR variants break the 8-bit GPU chains)
        for name, v in (("vp09", best(lambda c: c.startswith("vp09.00"))),
                        ("av01", best(lambda c: c.startswith("av01") and c.rsplit(".", 1)[-1] == "08"))):
            if v:
                res[name] = {"v": v["url"], "v_hdr": hdr(v), "a": a["url"] if a else None,
                             "a_hdr": hdr(a) if a else "", "width": v["width"], "height": v["height"],
                             "fps": v.get("fps") or 30, "codec": name}
    except Exception as e:
        print(f"  hi-res stream unavailable ({str(e)[:80]}); using local copy")
    return res


def parse_channel_line(line):
    """'URL | kw1, kw2  # note' -> (url, [keywords]). Empty url for blank/comment lines."""
    line = line.split("#")[0].strip()
    url, _, kws = line.partition("|")
    return url.strip(), [k.strip().lower() for k in kws.split(",") if k.strip()]


def latest_videos(channel_url, limit=5):
    """Newest video URLs on a channel (no download). 'URL | kw1, kw2' keeps only titles with a keyword."""
    url, keywords = parse_channel_line(channel_url)
    url = url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    opts = _base_opts() | {"extract_flat": True, "playlistend": limit * 8 if keywords else limit}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    out = []
    for e in info.get("entries", []):
        if not e.get("id"):
            continue
        if keywords and not any(k in (e.get("title") or "").lower() for k in keywords):
            continue
        out.append(f"https://www.youtube.com/watch?v={e['id']}")
    return out[:limit]
