# daily-run (11:00, the only scheduled task)

Before starting, read G:\gta6\docs\PLAYBOOK.md completely and apply it to every judgment call below.

You run the whole day of a YouTube pipeline in G:\gta6 on Windows (channel: ClipGTAGamer, GTA 6 news) in ONE run:
find what is trending, make Shorts and one narrated video, review them, and upload. There is NO Anthropic API key:
you yourself pick clips and write scripts. Use G:\gta6\.venv\Scripts\python.exe with working directory G:\gta6.
Downloads, renders and builds take 5-30 minutes each: run them in the background or with long timeouts.
Goal: use the full daily quota of 6 uploads = 5 Shorts + 1 narrated video, all Private.

In PowerShell, refresh PATH first so ffmpeg is found:
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
In Git Bash use forward slashes (`.venv/Scripts/python.exe`).

If a command prints "another clipper run is still going", wait 5 minutes and retry (up to 6 times); only one
clipper command can run at a time, so never start two in parallel.

## A. What is trending (10 min)
1. `python -m clipper stats` (refreshes workspace\insights.txt; if read access is missing, note it and go on).
2. `python -m clipper status` - first line shows today's upload count. If it is already 6/6, report and stop.
3. `python -m clipper library` then `python -m clipper trends`.
4. Search this week's most-viewed videos (filter `sp=CAMSBAgCEAE` = this week, sorted by views) for 4-6 queries
   that match what players search right now, e.g. "gta 6 hidden details", "gta 6 secrets", "gta 6 things you can
   do", "gta 6 tips and tricks", "gta 6 easter eggs", plus any new topic from `trends`:
   `python -m yt_dlp --flat-playlist --playlist-end 8 --print "%(id)s | %(channel)s | %(view_count)s | %(duration_string)s | %(title)s" "https://www.youtube.com/results?search_query=gta+6+hidden+details&sp=CAMSBAgCEAE"`
5. Choose (see PLAYBOOK section 3a):
   - 3 Shorts sources: narrated English videos 5-30 min (list videos, tips, tested secrets). Prefer channels that
     do well in insights.txt. Skip livestreams, multi-hour walkthroughs, reaction/funny-moment compilations full of
     profanity, GTA 5 mod videos, and anything not yet checked as a real GTA 6 topic.
   - 1-2 sources for the narrated video on ONE topic not used before (titles of workspace\explainers\*.json).
     A list video with continuous gameplay under the narration is ideal B-roll.

## B. Shorts
6. `python -m clipper prepare <url1> <url2> <url3> [<url4>]` (download + transcribe; 5-20 min).
7. For each new workspace\<id>\candidates.txt: read it fully and write picks.json (format and title rules are at the
   top of the file and in PLAYBOOK section 3). Aim for 2-3 clips per source, 25-45 s, one item per clip.
8. `python -m clipper finish`, then `python -m clipper review`. Open every short.sheet.jpg and approve/reject
   (PLAYBOOK section 4). If a good clip only fails because the source's own big text is cut off at the edges, do not
   reject it: set it back to "selected" in that video's clips.json, delete its clip folder's short* files, and
   re-render with the full-frame layout: `FRAMING=blur python -m clipper finish` (PowerShell: `$env:FRAMING="blur"`).
   You need at least 5 approved clips from today's sources; if short, pick more moments or one more source.

## C. Narrated video
9. Write workspace\explainers\<today YYYY-MM-DD>.json (schema, length and style rules: PLAYBOOK section 5).
10. Before building, check every B-roll range: make a frame grid of each range from workspace\<id>\source.mp4
    (one frame every 5-10 s with the time printed on it, see PLAYBOOK section 6) and look at it. Remove seconds
    that show another game (labels like "Grand Theft Auto V"), a webcam, menus or title cards.
11. `python -m clipper explain workspace\explainers\<today>.json` (10-25 min). Then look at final.sheet.jpg and a
    few frames from final.mp4. Wrong game, faces or broken frames -> fix ranges, delete the output folder, rebuild.
12. Open thumb.1-3.jpg and choose N (PLAYBOOK section 7).

## D. Upload (Private)
13. (If an upload fails with `uploadLimitExceeded`, wait 10 minutes and retry, up to 2 hours: see PLAYBOOK section 8.)
    `MAX_UPLOADS_PER_RUN=5 python -m clipper upload-pending` (PowerShell: `$env:MAX_UPLOADS_PER_RUN="5"`).
    It uploads the newest approved clips first.
14. `python -m clipper explain workspace\explainers\<today>.json --upload --pick N`
15. `python -m clipper status` and confirm 6/6.

On Sundays, if quota is left after D (it normally is not), you may also run the compilation steps from
docs\tasks\weekly-compilation.md; otherwise skip it.

Report: sources chosen and why, Shorts uploaded (https://youtube.com/shorts/<id>), rejected clips with reasons,
the video link and thumbnail used, and any errors. Do not change code, channels.txt or settings; if something is
broken, use the PLAYBOOK troubleshooting table, otherwise describe the error.
