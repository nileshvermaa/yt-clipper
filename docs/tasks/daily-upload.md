# daily-upload

Before starting, read G:\gta6\docs\PLAYBOOK.md and apply it to every judgment call below.

You run the daily UPLOAD step of a YouTube pipeline in G:\gta6 on Windows. Use G:\gta6\.venv\Scripts\python.exe with working directory G:\gta6. Uploads can take several minutes each: use generous timeouts.

In PowerShell, refresh PATH first:
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

If a command prints "another clipper run is still going", wait 10 minutes and try once more; if it still does, report that and stop.

Steps:
1. Run: .venv\Scripts\python.exe -m clipper upload-pending
   Uploads up to 4 approved Shorts (the per-run limit). "pacing" or "Daily upload limit reached" messages are normal: report them.
2. Today's narrated video: if workspace\explainers\<today YYYY-MM-DD>\info.json exists and its "status" is "review":
   a. Open workspace\explainers\<today>\final.sheet.jpg. Continue only if every frame is GTA 6 footage with the red channel tag top-right, and nothing is black or broken. Otherwise do NOT upload; report why.
   b. Open thumb.1.jpg, thumb.2.jpg, thumb.3.jpg in that folder. Choose N = the one with real game footage (character, car or city), no real people's photos, no tweets or text-heavy screenshots.
   c. Run: .venv\Scripts\python.exe -m clipper explain workspace\explainers\<today>.json --upload --pick N
   If there is no info.json for today, report that the 9 am production did not make a video.
3. Run: .venv\Scripts\python.exe -m clipper status   (first line shows today's upload count)

Report: Shorts uploaded with their https://youtube.com/shorts/<id> links, the video link and which thumbnail was used, and any errors. Do not change code or settings.