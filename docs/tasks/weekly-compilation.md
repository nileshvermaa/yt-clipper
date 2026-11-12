# weekly-compilation

Before starting, read G:\gta6\docs\PLAYBOOK.md and apply it to every judgment call below.

You run the weekly long-form compilation step of a YouTube pipeline in G:\gta6 on Windows. No Anthropic API key is used. Use G:\gta6\.venv\Scripts\python.exe with working directory G:\gta6. Rendering can take 10+ minutes: use generous timeouts or run in the background.

In PowerShell, refresh PATH first so ffmpeg is found:
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

Steps:
1. Run: .venv\Scripts\python.exe -m clipper compile
   It builds workspace\compilations\<today YYYY-MM-DD>.mp4 (about 10 min, 16:9) from the best approved/uploaded clips of the last 7 days, plus a 6-frame contact sheet <date>.sheet.jpg and <date>.json. If it says there are not enough fresh clips, report that and stop.
2. Open the contact sheet image and judge it. Approve only if every frame shows real GTA 6 footage or graphics, the "title | Credit: creator" bar is visible top-left, and there are no black, empty or broken frames. Also read <date>.json and check the title and chapter list look sensible. When unsure, do NOT approve; report why.
3. Open the three candidate thumbnails workspace\compilations\<date>.thumb.1.jpg, .thumb.2.jpg, .thumb.3.jpg. Choose N = the one whose background is real GTA 6 game footage (a character, car or city scene). Avoid photos of real people, tweets/screenshots or text-heavy images. If all three are poor, still pick the least bad and say so in the report.
   If good, run: .venv\Scripts\python.exe -m clipper compile --approve <date> --pick N
   then: .venv\Scripts\python.exe -m clipper compile --upload
   It uploads as Private and counts toward the daily limit of 6. If it fails with "Daily upload limit reached", report that; the next run of this task (or the user) can upload it later with "compile --upload".
   If it prints "thumbnail refused", the channel is not phone-verified yet; mention it in the report (the video is still uploaded).
4. Report: the compilation length, segment count, approve/reject decision with reason, which thumbnail was picked and whether it was set, and the https://youtube.com/watch?v=<id> link if uploaded.

Do not change code, channels.txt or settings. If something errors, describe the error instead of fixing code.