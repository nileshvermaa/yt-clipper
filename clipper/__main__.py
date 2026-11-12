"""CLI.

  python -m clipper auth                      one-time YouTube login
  python -m clipper run <url> [--upload]      clip one video (optionally upload)
  python -m clipper watch [--upload]          check channels.txt for new videos
  python -m clipper upload-pending            upload rendered clips not yet uploaded (respects quota)
  python -m clipper status                    show clips and quota use
  python -m clipper stats                     pull views/retention, refresh insights.txt

No-API-key mode (Claude in the app picks the clips):
  python -m clipper prepare [url ...]         download + transcribe -> workspace/<id>/candidates.txt
  python -m clipper awaiting                  list candidates.txt that need a picks.json
  python -m clipper finish [--upload]         picks.json -> render -> contact sheets (-> upload approved)
  python -m clipper review                    list clips waiting for review (contact sheet paths)
  python -m clipper approve <id> <n..>|--all  approve clips for upload   (reject: python -m clipper reject <id> <n..> -r why)
"""
import argparse
import json
from pathlib import Path

from . import config


def _clips_file(meta):
    return Path(meta["workdir"]) / "clips.json"


def _save_clips(meta, clips):
    _clips_file(meta).write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")


def process(url, do_upload=False):
    from . import download, render, select_clips, transcribe

    render.check_ffmpeg()
    print(f"[1/5] download {url}")
    meta = download.fetch(url)
    print(f"  '{meta['title']}' by {meta['channel']}  heatmap={'yes' if meta['heatmap'] else 'no'}")
    print("[2/5] transcribe")
    segs = transcribe.transcribe(meta)
    print("[3/5] select clips")
    clips = select_clips.select(meta, segs)
    for c in clips:
        print(f"  #{c['n']} {c['start']:.1f}-{c['end']:.1f}s ({c['end']-c['start']:.0f}s) score={c['score']}  {c['title']}")
    print("[4/5] render")
    for c in clips:
        if c["status"] == "selected":
            out = render.render(meta, segs, c)
            c["status"], c["file"] = "rendered", str(out)
            _save_clips(meta, clips)
            print(f"  -> {out}")
    if do_upload:
        print("[5/5] upload")
        upload_clips(meta, clips)
    else:
        print("[5/5] skipped upload (review clips, then: python -m clipper upload-pending)")
    return meta


def prepare(url):
    """No-API mode, part 1: download + transcribe + write candidates.txt for Claude."""
    from . import download, render, select_clips, transcribe
    render.check_ffmpeg()
    print(f"[prepare] {url}")
    meta = download.fetch(url)
    segs = transcribe.transcribe(meta)
    if _clips_file(meta).exists():
        print("  already has clips.json")
        return meta
    lang_file = Path(meta["workdir"]) / "language.txt"
    lang = lang_file.read_text(encoding="utf-8").strip() if lang_file.exists() else config.CHANNEL_LANGUAGE
    if lang != config.CHANNEL_LANGUAGE:
        reason = f"spoken language is '{lang}', channel language is '{config.CHANNEL_LANGUAGE}'"
        (Path(meta["workdir"]) / "skipped.txt").write_text(reason, encoding="utf-8")
        print(f"  SKIPPED: {reason}")
        return meta
    print(f"  -> {select_clips.prepare(meta, segs)}")
    return meta


def awaiting():
    """Videos whose candidates.txt still needs picks.json."""
    for meta, clips in all_videos():
        w = Path(meta["workdir"])
        if (w / "candidates.txt").exists() and not (w / "picks.json").exists() and not clips:
            yield w / "candidates.txt"


def finish(do_upload):
    """No-API mode, part 2: picks.json -> clips.json -> render (-> upload)."""
    from . import render, review, select_clips, transcribe
    render.check_ffmpeg()
    for meta, clips in all_videos():
        w = Path(meta["workdir"])
        if not clips and (w / "picks.json").exists():
            segs = transcribe.transcribe(meta)
            clips = select_clips.apply_picks(meta, segs)
        if not any(c["status"] in ("selected", "rendered") for c in clips):
            continue
        print(f"== {meta['title']}")
        segs = transcribe.transcribe(meta)
        for c in clips:
            if c["status"] == "selected":
                c["status"], c["file"] = "rendered", str(render.render(meta, segs, c))
                _save_clips(meta, clips)
                review.log(meta, f"clip {c['n']} rendered: {c['title']}")
                print(f"  -> {c['file']}")
        if config.REVIEW_BEFORE_UPLOAD:
            for c in review.prepare_review(meta, clips, lambda m, cl: _save_clips(m, cl)):
                print(f"  review: {c['sheet']}")
    if do_upload:
        cmd_upload_pending()


def new_channel_videos():
    from . import download, upload
    if not config.CHANNELS_FILE.exists():
        raise SystemExit("Create channels.txt with one channel URL per line.")
    state = upload._state()
    for line in config.CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        ch = line.split("#")[0].strip()
        if ch:
            for url in download.latest_videos(ch, limit=3):
                if url not in state["processed"]:
                    yield url


def mark_processed(url):
    from . import upload
    state = upload._state()
    state["processed"].append(url)
    upload.save_state(state)


_uploaded_this_run = [0]


def upload_clips(meta, clips):
    from . import review, upload
    ready = "approved" if config.REVIEW_BEFORE_UPLOAD else "rendered"
    for c in clips:
        if c["status"] != ready:
            continue
        gap = upload.minutes_since_last_upload()
        if _uploaded_this_run[0] == 0 and gap is not None and gap < config.MIN_UPLOAD_GAP_MIN:
            print(f"  pacing: last upload {gap:.0f} min ago (min gap {config.MIN_UPLOAD_GAP_MIN}); the rest waits for the next run")
            return False
        if _uploaded_this_run[0] >= config.MAX_UPLOADS_PER_RUN:
            print(f"  pacing: {config.MAX_UPLOADS_PER_RUN} uploads this run; the rest waits")
            return False
        try:
            vid = upload.upload(c["file"], meta, c)
        except RuntimeError as e:
            print(f"  stop: {e}")
            return False
        c["status"], c["youtube_id"] = "uploaded", vid
        _uploaded_this_run[0] += 1
        review.log(meta, f"clip {c['n']} uploaded as {vid} ({config.PRIVACY})")
        _save_clips(meta, clips)
        print(f"  uploaded https://youtube.com/shorts/{vid}")
    return True


def all_videos():
    for meta_file in sorted(config.WORKSPACE.glob("*/meta.json")):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        cf = _clips_file(meta)
        clips = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else []
        yield meta, clips


def cmd_watch(do_upload):
    from . import download, upload
    if not config.CHANNELS_FILE.exists():
        raise SystemExit("Create channels.txt with one channel URL per line.")
    state = upload._state()
    for line in config.CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        ch = line.split("#")[0].strip()
        if not ch:
            continue
        print(f"== {ch}")
        for url in download.latest_videos(ch, limit=3):
            if url in state["processed"]:
                continue
            try:
                process(url, do_upload)
            except Exception as e:  # keep going with other videos
                print(f"  FAILED {url}: {e}")
                continue
            state = upload._state()
            state["processed"].append(url)
            upload.save_state(state)


def cmd_upload_pending():
    for meta, clips in all_videos():
        if any(c["status"] == ("approved" if config.REVIEW_BEFORE_UPLOAD else "rendered") for c in clips):
            print(f"== {meta['title']}")
            if not upload_clips(meta, clips):
                return


def cmd_status():
    from . import upload
    day, n = upload.uploads_today()
    print(f"Uploads today ({day}): {n}/{config.DAILY_UPLOAD_LIMIT}")
    for meta, clips in all_videos():
        print(f"\n{meta['id']}  {meta['title'][:60]}")
        for c in clips:
            print(f"  #{c['n']} [{c['status']}] {c['title']}")


def cmd_review():
    """Make sheets for any freshly rendered clips, then list everything waiting."""
    from . import review
    n = 0
    for meta, clips in all_videos():
        review.prepare_review(meta, clips, lambda m, cl: _save_clips(m, cl))
        for c in clips:
            if c["status"] == "review":
                n += 1
                print(f"{meta['id']} #{c['n']}  {c['title']}")
                print(f"   sheet: {c['sheet']}")
    print(f"{n} clip(s) waiting for review" if n else "nothing waiting for review")


def cmd_mark(a, status):
    from . import review
    for meta, clips in all_videos():
        if meta["id"] != a.video:
            continue
        for c in clips:
            if c["status"] in ("review", "rendered", "approved") and (a.all or c["n"] in a.n):
                c["status"] = status
                if status == "rejected":
                    c["reason"] = a.reason or "rejected on review"
                review.log(meta, f"clip {c['n']} {status}" + (f": {c['reason']}" if status == "rejected" else ""))
                print(f"  #{c['n']} -> {status}")
        _save_clips(meta, clips)


def _secs(s):
    """'75' -> 75.0, '1:15' -> 75.0, '1:02:03' -> 3723.0"""
    t = 0.0
    for part in str(s).split(":"):
        t = t * 60 + float(part)
    return t


def cmd_versus(a):
    from . import render, versus
    render.check_ffmpeg()
    (ua, sa, ea), (ub, sb, eb) = a.a, a.b
    final, ma, mb = versus.build(ua, _secs(sa), _secs(ea), ub, _secs(sb), _secs(eb),
                                 a.label_a, a.label_b, a.logo_a, a.logo_b)
    print(f"  -> {final}")
    if not a.upload:
        print("  review it, then re-run with --upload to publish")
        return
    from . import upload
    clip = {
        "title": a.title or f"{a.label_a} vs {a.label_b}",
        "description": f"{a.label_a} vs {a.label_b}, side by side.\n\nFootage: {ma['channel']} ({ma['url']}) and {mb['channel']} ({mb['url']})",
        "tags": [a.label_a, a.label_b, "GTA 6", "GTA VI", "comparison"],
    }
    meta = {"url": ma["url"], "channel": f"{ma['channel']} & {mb['channel']}", "channel_url": ""}
    vid = upload.upload(final, meta, clip)
    print(f"  uploaded https://youtube.com/shorts/{vid}")


LOCK_CMDS = {"run", "watch", "prepare", "finish", "upload-pending", "compile", "explain"}
PREPARE_TIMEOUT_SEC = 3600  # one video: download + Whisper; a stuck child is killed after this


def _single_instance():
    """Hold an OS lock for this process's life so two pipeline runs never overlap (released on exit or crash)."""
    import msvcrt
    import os
    f = open(config.WORKSPACE / ".lock", "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit("another clipper run is still going; exiting")
    os.environ["CLIPPER_LOCKED"] = "1"  # children of this run skip the lock
    return f


def _kill_tree(pid):
    import subprocess
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)


def main():
    import os
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="clipper")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    r = sub.add_parser("run"); r.add_argument("url"); r.add_argument("--upload", action="store_true")
    w = sub.add_parser("watch"); w.add_argument("--upload", action="store_true")
    sub.add_parser("upload-pending")
    sub.add_parser("status")
    tr = sub.add_parser("trends", help="newest GTA 6 videos on YouTube ranked by views (topic ideas)")
    tr.add_argument("query", nargs="?", default="GTA 6")
    sub.add_parser("stats", help="pull views/retention of uploaded videos and refresh insights.txt")
    pr = sub.add_parser("prepare", help="no-API mode: download+transcribe, write candidates.txt")
    pr.add_argument("urls", nargs="*", help="video URLs; omit to use new videos from channels.txt")
    sub.add_parser("awaiting", help="list candidates.txt files that still need picks.json")
    f = sub.add_parser("finish", help="no-API mode: picks.json -> render"); f.add_argument("--upload", action="store_true")
    cp = sub.add_parser("compile", help="weekly 16:9 compilation from approved clips")
    cp.add_argument("--days", type=int, default=7); cp.add_argument("--approve", metavar="DATE")
    cp.add_argument("--thumb", metavar="DATE", help="make + set the custom thumbnail of an uploaded compilation")
    cp.add_argument("--pick", type=int, default=1, help="which candidate thumbnail (1-3) to use")
    cp.add_argument("--upload", action="store_true", help="upload approved compilations")
    ex = sub.add_parser("explain", help="narrated explainer video from a script.json")
    ex.add_argument("script"); ex.add_argument("--upload", action="store_true")
    ex.add_argument("--pick", type=int, default=1, help="which candidate thumbnail (1-3)")
    sub.add_parser("review", help="contact sheets for clips waiting for approval")
    for name in ("approve", "reject"):
        ap = sub.add_parser(name); ap.add_argument("video"); ap.add_argument("n", nargs="*", type=int)
        ap.add_argument("--all", action="store_true"); ap.add_argument("-r", "--reason", default="")
    v = sub.add_parser("versus", help="two videos back to back, e.g. GTA V then GTA VI")
    v.add_argument("--a", nargs=3, required=True, metavar=("URL", "START", "END"), help="first video + time range (seconds or m:ss)")
    v.add_argument("--b", nargs=3, required=True, metavar=("URL", "START", "END"), help="second video + time range")
    v.add_argument("--label-a", default="GTA V"); v.add_argument("--label-b", default="GTA VI")
    v.add_argument("--logo-a", help="optional PNG shown on top of the first half instead of the text label")
    v.add_argument("--logo-b", help="optional PNG for the second half")
    v.add_argument("--title", help="Short title (default: '<label-a> vs <label-b>')")
    v.add_argument("--upload", action="store_true")
    a = p.parse_args()
    if a.cmd in LOCK_CMDS and not os.environ.get("CLIPPER_LOCKED"):
        _lock = _single_instance()  # noqa: F841  kept open until exit

    if a.cmd == "versus":
        cmd_versus(a)
        return

    if a.cmd == "compile":
        from . import compile as comp
        from . import render; render.check_ffmpeg()
        if a.thumb:
            info = comp.set_thumb(a.thumb, a.pick)
            print(f"  thumbnail {'set' if info['thumb_set'] else 'made, not set'}: {info['thumb']}")
        elif a.approve:
            j = comp.OUT / f"{a.approve}.json"
            info = json.loads(j.read_text(encoding="utf-8")); info["status"] = "approved"
            if info.get("thumbs"):
                info["thumb"] = info["thumbs"][min(a.pick, len(info["thumbs"])) - 1]
            j.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"); print(f"  {j.name} approved")
        elif a.upload:
            comp.upload_ready()
        else:
            j, info, t = comp.build(a.days)
            print(f"  {len(info['used'])} segments, {t / 60:.1f} min -> {info['file']}")
            print(f"  sheet: {j.with_suffix('.sheet.jpg')}")
        return
    if a.cmd == "explain":
        from . import explainer, render
        render.check_ffmpeg()
        if a.upload:
            info = explainer.upload_it(a.script, a.pick)
            print(f"  uploaded https://youtube.com/watch?v={info['youtube_id']}  thumbnail set: {info['thumb_set']}")
        else:
            work, info, t = explainer.build(a.script)
            print(f"  {t / 60:.1f} min -> {info['file']}")
            print(f"  review: {work / 'final.sheet.jpg'} and thumbnails {', '.join(info['thumbs'])}")
        return
    if a.cmd == "review":
        cmd_review()
        return
    if a.cmd in ("approve", "reject"):
        cmd_mark(a, "approved" if a.cmd == "approve" else "rejected")
        return
    if a.cmd == "prepare":
        if len(a.urls) == 1:
            prepare(a.urls[0])
            sys.stdout.flush()
            os._exit(0)  # skip CUDA/ctranslate2 teardown, which can hang or crash after Whisper
        # Each video in its own process: the CUDA runtime can crash on exit after transcription
        # (the transcript is already saved), so a retry just picks up from the cache.
        import subprocess
        import sys
        for url in a.urls or list(new_channel_videos())[:config.PREPARE_MAX_VIDEOS]:
            for attempt in range(2):
                proc = subprocess.Popen([sys.executable, "-u", "-m", "clipper", "prepare", url])
                try:
                    proc.wait(timeout=PREPARE_TIMEOUT_SEC)
                except subprocess.TimeoutExpired:
                    print(f"  {url} took over {PREPARE_TIMEOUT_SEC // 60} min; killing it")
                    _kill_tree(proc.pid)
                    proc.wait()
                r = proc
                if r.returncode == 0:
                    mark_processed(url)
                    break
            else:
                print(f"  FAILED {url} (exit {r.returncode})")
        return
    if a.cmd == "awaiting":
        for path in awaiting():
            print(path)
        return
    if a.cmd == "finish":
        finish(a.upload)
        return

    if a.cmd == "auth":
        from . import upload
        upload.authorize()
    elif a.cmd == "run":
        process(a.url, a.upload)
    elif a.cmd == "watch":
        cmd_watch(a.upload)
    elif a.cmd == "upload-pending":
        cmd_upload_pending()
    elif a.cmd == "status":
        cmd_status()
    elif a.cmd == "trends":
        from . import download
        for views, dur, title, channel, url in download.trends(a.query):
            print(f"{views:>9,}  {dur // 60:>2}m  {title[:70]}  | {channel}  {url}")
    elif a.cmd == "stats":
        from . import analytics
        print(f"  updated stats for {analytics.fetch()} videos")
        text, n = analytics.insights()
        print(text or f"  {n} public Shorts old enough to judge; insights start at {analytics.MIN_SAMPLES}")


if __name__ == "__main__":
    main()
