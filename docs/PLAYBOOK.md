# Editing playbook

Everything an operator (a person or any AI model) needs to produce the same quality every day. The code enforces
what it can; this file holds the judgment calls. The scheduled tasks in `docs/tasks/` reference it.

## 1. Daily output and load

- One scheduled run a day at 11:00 (`docs/tasks/daily-run.md`): trend search -> 5 Shorts + 1 narrated video ->
  review -> upload. YouTube quota allows 6 uploads/day; the quota day follows Pacific time, so `status` can show
  yesterday's date in the morning in India. The weekly compilation is manual now (`docs/tasks/weekly-compilation.md`).
- Only one clipper command runs at a time (file lock). Do not start manual runs while the 11:00 run is working:
  a blocked `explain` simply exits and that day's video is lost.
- `PREPARE_MAX_VIDEOS=2` new downloads per run, `CPU_THREADS=3`, decode/scale/encode on the GPU. One run at a time
  (file lock). `MAX_UPLOADS_PER_RUN` is 4 in `.env`; the daily run overrides it to 5 for one command. Never raise the others to "catch up"; the backlog of approved clips is the buffer.
- Everything uploads **Private**. A human makes videos public. `upload-pending` takes the newest downloads first,
  so fresh news goes out before the older backlog.

## 2. Picture quality (why things looked like 360p, and the rules that fixed it)

| Rule | Reason | Enforced by |
|---|---|---|
| Never render from `workspace/<id>/source.mp4` | it is a 1.3-2.9 Mbps analysis copy | `download.fetch_range` / `stream_inputs` fetch the best 8-bit stream (up to 4K) for just the needed seconds |
| No 9:16 crop from sources under 1440p | a 608 px crop upscaled to 1080 is soft | `MIN_CROP_HEIGHT`; such clips use the full-frame layout |
| Long-form renders at 2560x1440 | YouTube gives 1440p uploads its better encoder | `compile.W, H` |
| Judge quality after YouTube finishes HD processing | fresh uploads play at 360p for up to an hour | wait before judging |

## 3. Shorts: picking clips

- Open with a hook in the first sentence; understandable alone; end on a finished thought; 25-75 s, shorter is
  better (under 35 s clips are replayed; long ones lose ~80% of viewers on this channel).
- Opening line (rules borrowed from SupoClip's opening review): never start on a dangling conjunction ("But",
  "And", "Because", "So that's why"), on a 1-2 word fragment ("No. No? Ah!"), or on banter before the point. Move
  the start to the first self-contained sentence; if that loses more than ~15 s or the point, pick another moment.
- In list videos ("50 details", "20 secrets"), one item = one clip: start where the item is named, end when the
  narrator moves to the next one.
- Skip ads, sponsor reads, "subscribe" asks, and rumors naming real people.
- Reject clips whose footage is another game (GTA 5 / Red Dead comparisons are common in "everything you need to
  know" videos), even when the narration is about GTA 6.
- Title: 3-7 words, under 45 characters, "GTA 6" early, one word in CAPS, ends with "..." or "!?". True to the clip.
  Concrete news hooks win ("Kodak Black is IN GTA 6"); "Concept"/"Fan Concept" titles flop.
- If `candidates.txt` ends with "WHAT WORKS ON THIS CHANNEL", follow it: it is this channel's own analytics.

## 3a. Finding trending sources

- `trends` alone is not enough after launch: also search YouTube for this week's most-viewed videos (filter
  `sp=CAMSBAgCEAE`) with the phrases players type: "hidden details", "secrets", "things you can do", "tips and
  tricks", "easter eggs", "first mission". Topics that worked: launch reviews (IGN, gameranx), "50 details" lists
  (T5G), missables and money tips (BiggySweats), easter eggs (ZacCoxTV), car/weapon mechanics (HarmNone).
- Best Shorts sources are narrated list/tips videos (one item = one clip, 25-45 s). Poor sources: livestreams and
  multi-hour walkthroughs (no hooks, huge downloads), funny-moment compilations (profanity, source captions),
  facecam-heavy "testing" videos, "everything you need to know" videos that cut to GTA 5 / Red Dead footage,
  and "GTA 6 mods/cheats" results (almost all GTA 5 mods or clickbait in launch week).
- Never re-upload someone's full video or full mission playthrough (copyright strikes, reused-content
  demonetisation). Make a narrated breakdown with short credited excerpts instead.
- Story topics (first mission, endings) are allowed with "(SPOILERS)" in the title and thumbnail badge.

## 4. Shorts: review (contact sheet) - reject when unsure

Approve only if: picture sharp; subject in frame; on-screen text readable and not clipped at the edges; our captions
do not sit on the source's own big captions or on stream chat; no black/loading frames; not a near-duplicate.
Known bad sources for cropping: channels with huge burned-in captions (Hazard), live streams with chat overlays.
- Source's big title text cut off at the edges, but the clip is good: re-render it full-frame instead of rejecting
  (status back to `selected`, delete `clipN/short*`, run `FRAMING=blur python -m clipper finish`).
- Reject: a webcam face filling the frame in most of the sheet, footage of another game, a clip that runs into the
  narrator's next item, a source caption sitting on top of ours, grey/broken frames.
- The `reaction` layout (gameplay on top, facecam below) is acceptable when the gameplay half shows the topic.

## 5. Narrated video: script

- Topic: from `python -m clipper trends`: this week's most-viewed uploads, what people are searching on YouTube
  right now, and Rockstar's newest official uploads. A new official upload is always the top topic. Real GTA 6 news only; one topic per video;
  never a topic already in `workspace/explainers/*.json`.
- 6-8 sections, 550-750 words. Audience: GTA fans aged 16-30. Hook in sentence one, short spoken sentences,
  one idea per section, a question for the comments and a subscribe ask at the end.
- Original commentary in your own words. Attribute ("Rockstar confirmed", "according to previews"); mark rumors
  as rumors; say only what the source transcripts support; no profanity.
- Spell numbers as words ("thirty frames per second"); "GTA 6" and "PS5" stay as they are. `explain` refuses
  scripts with multi-digit numbers, wrong length, or unprepared videos and says why.

## 6. Narrated video: footage and look

- `broll` ranges: 60-150 s where that topic is discussed **and game footage is on screen**. If a source shows
  another game or mostly a webcam, take footage from another prepared GTA 6 video and keep the original in `sources`.
- **Prefer official footage.** `workspace/library.json` lists Rockstar's own trailers (prepared by
  `python -m clipper library`, 4K, no creator overlays). Use their ids in `broll` whenever the section is general
  (intro, story, characters, outro). Use creators' footage only when the section needs that specific material.
  A section whose footage is all unusable falls back to official footage automatically.
- Automatic: branded intro (4.5 s, channel name) and outro (10 s, room for end-screen cards) from `assets/brand/intro.mp4` and
  `outro.mp4` (Gemini/Veo clips, not committed; trimmed and cached as `*.ready.mp4`). Delete the `.ready.mp4` to rebuild.
- Automatic: burned-in captions (5 words at a time, timed to the voice); quiet music bed if `assets/music/` has
  tracks; light sharpening when footage is below 1440p; 5 s cuts; text cards, black frames and webcam faces are skipped; voice `am_michael` at speed 1.05,
  synthesized per sentence; title card, sliding yellow headings with a red bar, channel tag top-right, footage
  credit bottom-right, subscribe card. Do not change fonts/colours per video: consistency is the brand.
- Check ranges BEFORE building (the six-frame sheet misses most problems). One grid per range, time stamped:
  `ffmpeg -ss A -t LEN -i workspace/<id>/source.mp4 -vf "fps=1/5,scale=240:-1,drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':text='%{eif\:t+A\:d}':fontcolor=yellow:fontsize=24,tile=10x2" -frames:v 1 grid.jpg`
  Review sites compare with older games (IGN's review showed GTA 4/5 bank heists with a "Grand Theft Auto V" label)
  and cut to the reviewer's webcam; split ranges around those seconds (each range at least 30 s).
- After building, open `final.sheet.jpg` and grab a few frames from `final.mp4`. Wrong game, a face, or broken
  frames -> fix the ranges and rebuild. A single glitch frame from the source's own transition is acceptable.
- Extra videos on a day that already has `<today>.json`: use another file name (`hidden-details.json`); never
  overwrite the dated script, the daily run uses it.

## 7. Thumbnails

Pick the candidate with real game footage (character, car, city). Never a real person's photo, a tweet, or a
text-heavy screenshot. Headline 2-3 words in caps. Shorts thumbnails cannot be set by API.

## 8. When something breaks

| Symptom | Cause / fix |
|---|---|
| `uploadLimitExceeded` (HTTP 400) | YouTube's own rolling-24-hour channel limit, separate from our 6/day counter. Uploads from the previous day's run still count until 24 h have passed, so a run earlier than yesterday's hits it. Wait and retry every 10 min; keep the daily run at a fixed time |
| "another clipper run is still going" | a run is active; wait. Stale python processes: kill them, the lock frees itself |
| `ModuleNotFoundError` | use `.venv\Scripts\python.exe`, not system Python |
| ffmpeg not found | refresh PATH (see task files) |
| voice-over "looks garbled" | rephrase that section into shorter sentences and rebuild |
| "Sign in to confirm your age" | that video needs `secrets/cookies.txt`; it is skipped, pick another source |
| "no music" | optional: add royalty-free tracks to `assets/music/` |
| "hi-res B-roll failed" | YouTube throttled; the low-bitrate copy was used. Rebuild later for full quality |
| "thumbnail refused" | custom thumbnails not enabled: youtube.com/features |
| "stats need read access" | run `python -m clipper auth` again |
| Whisper crash on exit | harmless; transcript is saved, the retry picks it up |
| Do not upgrade | `ctranslate2==4.5.0`, `onnxruntime-gpu==1.19.2`; install `kokoro-onnx` with `--no-deps` |

## 9. Changing the pipeline

Change code, run `ruff check .` and `pytest -q`, update this file and `docs/tasks/*.md` in the same commit, push.
The scheduled tasks read `docs/tasks/*.md` at run time, so the repo is the single source of truth.

## 10. Decisions and research (so nobody repeats them)

- No Anthropic API key, by choice: the assistant running the scheduled task picks clips and writes scripts.
- OpusClip / Vyro (ImagineArt): free tiers are watermarked, expire or need credit; OpusClip's API needs a paid
  plan. Not integrated. Fine for occasional manual use (a second opinion on clip picks, channel art).
- SupoClip (github.com/FujiwaraChoki/supoclip): needs Docker, Postgres, a web frontend and an OpenAI/Anthropic/
  Google key; noncommercial licence (individual creators allowed). Not installed; its clip-opening rules are in
  section 3.
- Real-ESRGAN upscaling: too heavy for the RTX 3050; `cas` sharpening is used instead.
- Reddit trends: blocked (403) for scripts; Rockstar Newswire is JS-only, so Rockstar's YouTube channel is used.
- Music: 12 tracks from the YouTube Audio Library channel in `assets/music/` (not committed). Scott Buckley tracks
  (track07, track08) may need credit in the description. Bandcamp "onemansymphony" had no usable licensed music.
- Brand: intro/outro made with Gemini (Veo), stored in `assets/brand/`; Shorts get no intro/outro (75 s limit).
- Analytics so far: clips under 35 s get ~85% watched and the most views; T5G and DarkViperAU sources do best,
  Hazard and DubStepZz worst; "Concept" titles flop.
