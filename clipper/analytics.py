"""Feedback loop: pull views/retention for uploaded videos, summarize what works, feed it into clip picking."""
import datetime as dt
import json
from collections import defaultdict
from statistics import mean

from . import config, upload

INSIGHTS = config.WORKSPACE / "insights.txt"
MIN_AGE_DAYS = 2   # analytics lag ~2 days and Shorts need time to get distributed
MIN_SAMPLES = 8    # below this the averages are noise
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _uploaded():
    """Every uploaded item as (youtube_id, save_fn, record, info); info has title/channel/dur/kind."""
    items = []
    for meta_file in config.WORKSPACE.glob("*/meta.json"):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        cf = meta_file.parent / "clips.json"
        if not cf.exists():
            continue
        clips = json.loads(cf.read_text(encoding="utf-8"))

        def save(cf=cf, clips=clips):
            cf.write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")
        for c in clips:
            if c.get("youtube_id"):
                items.append((c["youtube_id"], save, c, {"title": c["title"], "channel": meta["channel"],
                                                         "dur": c["end"] - c["start"], "kind": "short"}))
    for j in (config.WORKSPACE / "compilations").glob("*.json"):
        info = json.loads(j.read_text(encoding="utf-8"))
        if info.get("youtube_id"):
            def save(j=j, info=info):
                j.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
            items.append((info["youtube_id"], save, info, {"title": info["title"], "channel": "compilation",
                                                           "dur": 0, "kind": "long"}))
    return items


def fetch():
    """Update rec['stats'] for every uploaded video. Data API costs 1 quota unit per 50 videos."""
    items = _uploaded()
    if not items:
        return 0
    if not upload.granted("https://www.googleapis.com/auth/youtube.readonly"):
        raise SystemExit("  stats need read access: run `python -m clipper auth` once (see SETUP.md, analytics)")
    by_id = {vid: rec for vid, _, rec, _ in items}
    ids = list(by_id)
    yt = upload._service()
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="statistics,status,snippet", id=",".join(ids[i:i + 50])).execute()
        for v in resp.get("items", []):
            st = v["statistics"]
            pub = dt.datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
            by_id[v["id"]]["stats"] = by_id[v["id"]].get("stats", {}) | {
                "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)), "privacy": v["status"]["privacyStatus"],
                "age_days": round((now - pub).total_seconds() / 86400, 1),
                "fetched": now.isoformat(timespec="minutes")}
    if upload.granted(ANALYTICS_SCOPE):
        ya = upload._service("youtubeAnalytics", "v2")
        for i in range(0, len(ids), 200):
            resp = ya.reports().query(ids="channel==MINE", startDate="2020-01-01", endDate=now.date().isoformat(),
                                      metrics="views,averageViewPercentage,averageViewDuration,subscribersGained",
                                      dimensions="video", filters="video==" + ",".join(ids[i:i + 200]),
                                      maxResults=200).execute()
            for vid, _, pct, avg_dur, subs in resp.get("rows", []):
                by_id[vid].setdefault("stats", {}).update(
                    {"retention_pct": round(pct, 1), "avg_view_sec": round(avg_dur, 1), "subs_gained": int(subs)})
    else:
        print("  retention needs the analytics permission: run `python -m clipper auth` once more")
    for _, save, _, _ in items:  # rewrites a clips.json once per clip; files are tiny
        save()
    return len(ids)


def summarize(rows):
    """rows: dicts with title, channel, dur, kind, views, retention_pct (optional). Returns text or None."""
    rows = [r for r in rows if r["kind"] == "short"]
    if len(rows) < MIN_SAMPLES:
        return None
    lines = [f"Based on {len(rows)} public Shorts at least {MIN_AGE_DAYS} days old:"]
    by_ch = defaultdict(list)
    for r in rows:
        by_ch[r["channel"]].append(r)
    ranked = sorted(by_ch.items(), key=lambda kv: -mean(r["views"] for r in kv[1]))

    def fmt(ch, rs):
        return f"{ch} ({len(rs)} Shorts, avg {mean(r['views'] for r in rs):,.0f} views)"
    lines.append("Best source channels: " + "; ".join(fmt(c, rs) for c, rs in ranked[:3]))
    if len(ranked) > 3:  # only channels not already listed as best
        lines.append("Weakest source channels: " + "; ".join(fmt(c, rs) for c, rs in ranked[3:][-2:]))
    parts = []
    for name, lo, hi in (("under 35s", 0, 35), ("35-55s", 35, 55), ("over 55s", 55, 999)):
        rs = [r for r in rows if lo <= r["dur"] < hi]
        if rs:
            ret = [r["retention_pct"] for r in rs if r.get("retention_pct") is not None]
            parts.append(f"{name}: avg {mean(r['views'] for r in rs):,.0f} views"
                         + (f", {mean(ret):.0f}% watched" if ret else ""))
    lines.append("By length: " + "; ".join(parts))
    top = sorted(rows, key=lambda r: -r["views"])
    lines.append("Titles that worked: " + " | ".join(f"{r['title']} ({r['views']:,})" for r in top[:5]))
    lines.append("Titles that flopped: " + " | ".join(f"{r['title']} ({r['views']:,})" for r in top[-3:]))
    lines.append("Pick moments and write titles more like the ones that worked; prefer the length that holds viewers.")
    return "\n".join(lines)


def insights():
    """Rebuild workspace/insights.txt from stored stats. Returns (text or None, sample count)."""
    rows = []
    for _, _, rec, info in _uploaded():
        s = rec.get("stats", {})
        if s.get("privacy") == "public" and s.get("age_days", 0) >= MIN_AGE_DAYS:
            rows.append(info | {"views": s.get("views", 0), "retention_pct": s.get("retention_pct")})
    text = summarize(rows)
    if text:
        INSIGHTS.write_text(text, encoding="utf-8")
    elif INSIGHTS.exists():
        INSIGHTS.unlink()  # stale insights are worse than none
    return text, len([r for r in rows if r["kind"] == "short"])
