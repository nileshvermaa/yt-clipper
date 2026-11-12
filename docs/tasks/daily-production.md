# daily-production

Before starting, read G:\gta6\docs\PLAYBOOK.md and apply it to every judgment call below.

You run the daily PRODUCTION step of a YouTube pipeline in G:\gta6 on Windows (channel: ClipGTAGamer, GTA 6 news). There is NO Anthropic API key: you yourself pick clips and write scripts. Use G:\gta6\.venv\Scripts\python.exe with working directory G:\gta6. Long commands can take 10+ minutes; use generous timeouts or run them in the background. This task NEVER uploads: a separate task uploads at 1 pm.

Before running commands in PowerShell, refresh PATH so ffmpeg is found:
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

If any command prints "another clipper run is still going", report that and stop this run.

PART A - Shorts (goal: at least 4 approved clips waiting)
0. Run: .venv\Scripts\python.exe -m clipper stats
   Refreshes analytics and workspace\insights.txt. If read access is missing, note it and continue.
1. Run: .venv\Scripts\python.exe -m clipper status   and count clips marked [approved]. If 8 or more are already approved, skip to PART B.
2. Run: .venv\Scripts\python.exe -m clipper prepare   (downloads at most 2 new videos from channels.txt), then: .venv\Scripts\python.exe -m clipper awaiting
3. For EACH listed candidates.txt (at most 3 this run, newest first): read it fully. It has the rules and transcript lines "[line|seconds] text", windows divided by "---". Choose the best clips exactly as the rules say (strong hook in the first sentence, understandable alone, ends on a finished thought, within the stated duration, never crossing a "---", non-overlapping, best first). Skip ads, sponsor reads, subscribe requests, and rumors naming real people. Write picks.json in the SAME folder:
   {"clips": [{"start_line": int, "end_line": int, "title": "...", "description": "1-2 sentences of context", "tags": ["up to 8"], "score": 1-10}]}
   Title style: 3-7 words, under 45 characters, "GTA 6" early, one key word in CAPS, end with "..." or "!?" (e.g. "GTA 6 has a BIG Problem...", "Why GTA 6 has NO ..."). True to the clip. No emoji, no hashtags. If candidates.txt ends with "WHAT WORKS ON THIS CHANNEL", follow it. Check durations with the seconds stamps.
4. Run: .venv\Scripts\python.exe -m clipper finish   (renders, checks, writes short.sheet.jpg per clip)
5. Run: .venv\Scripts\python.exe -m clipper review   For EACH sheet, open the image. Approve only if: the picture is sharp, the subject is in frame and not cut off, on-screen text is readable and not clipped, our captions do not overlap the source's own big captions or stream chat, no black/empty frames, not a near-duplicate. Approve: .venv\Scripts\python.exe -m clipper approve <video_id> <n> ...   Reject: .venv\Scripts\python.exe -m clipper reject <video_id> <n> -r "reason". When unsure, reject.

PART B - today's narrated video (script file: workspace\explainers\<today YYYY-MM-DD>.json; skip PART B if workspace\explainers\<today>\info.json already exists)
6. Run: .venv\Scripts\python.exe -m clipper library   (keeps Rockstar's official trailers ready as clean B-roll; fast when nothing is new), then: .venv\Scripts\python.exe -m clipper trends   It lists this week's most-viewed GTA 6 videos, current YouTube searches and Rockstar's newest uploads. Pick ONE topic that is real GTA 6 news (not GTA 5 mods, vlogs, reactions, or anything used in an earlier workspace\explainers\*.json) and the 2 best videos about it (3-25 minutes long).
7. Run: .venv\Scripts\python.exe -m clipper prepare <url1> <url2>   Then read both transcripts: workspace\<video_id>\transcript.json (list of segments with "start" seconds and "text").
8. Write workspace\explainers\<today>.json:
   {"title": "max 45 chars, no 'GTA 6' prefix (the title card adds it)", "thumb": {"top": "GTA 6", "headline": "2-3 WORDS IN CAPS", "badge": "2 WORDS"}, "description": "2-3 sentences", "tags": ["up to 10"], "sources": ["<video_id>", "<video_id>"],
    "sections": [{"heading": "max 34 chars", "text": "narration", "broll": [["<video_id>", start_sec, end_sec]]}]}
   Rules: 6-8 sections, 550-750 words total (about 4-5 minutes). Write the narration IN YOUR OWN WORDS as original commentary for GTA fans aged 16-30: hook in the first sentence, short spoken sentences, one idea per section, attribute claims ("according to previews", "Rockstar confirmed"), no profanity, never copy the creators' sentences, state only what the transcripts support, mark rumors as rumors. Spell numbers as words ("thirty frames per second"). End with a question for the comments and a subscribe ask. Each section's broll: 1-2 ranges of 60-150 seconds from the moments where that topic is discussed and GAME FOOTAGE is on screen. Prefer the official Rockstar videos listed in workspace\library.json (use their "id") for general sections; use the creators' footage only where that specific material is needed. If a source video shows a different game or mostly a webcam, never use it for broll (still list it under "sources").
9. Run: .venv\Scripts\python.exe -m clipper explain workspace\explainers\<today>.json   Then open workspace\explainers\<today>\final.sheet.jpg. If frames show another game, a webcam face, or broken images, fix the broll ranges in the json, delete the folder workspace\explainers\<today>, and run it once more.

Finish with a short report: clips picked/approved/rejected (with reasons), how many approved clips are waiting, today's video title and length, and any errors. Do not change code, channels.txt or settings; if something is broken, describe the error instead.