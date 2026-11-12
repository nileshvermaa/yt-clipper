# Editing playbook

Everything an operator (a person or any AI model) needs to produce the same quality every day. The code enforces
what it can; this file holds the judgment calls. The scheduled tasks in `docs/tasks/` reference it.

## 1. Daily output and load

- 4 Shorts + 1 narrated video per day, uploaded at 13:00; 1 compilation on Sunday. YouTube quota allows 6 uploads/day.
- `PREPARE_MAX_VIDEOS=2` new downloads per run, `CPU_THREADS=3`, decode/scale/encode on the GPU. One run at a time
  (file lock). Never raise these to "catch up"; the backlog of approved clips is the buffer.
- Everything uploads **Private**. A human makes videos public.

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
- Skip ads, sponsor reads, "subscribe" asks, and rumors naming real people.
- Title: 3-7 words, under 45 characters, "GTA 6" early, one word in CAPS, ends with "..." or "!?". True to the clip.
  Concrete news hooks win ("Kodak Black is IN GTA 6"); "Concept"/"Fan Concept" titles flop.
- If `candidates.txt` ends with "WHAT WORKS ON THIS CHANNEL", follow it: it is this channel's own analytics.

## 4. Shorts: review (contact sheet) - reject when unsure

Approve only if: picture sharp; subject in frame; on-screen text readable and not clipped at the edges; our captions
do not sit on the source's own big captions or on stream chat; no black/loading frames; not a near-duplicate.
Known bad sources for cropping: channels with huge burned-in captions (Hazard), live streams with chat overlays.

## 5. Narrated video: script

- Topic: from `python -m clipper trends` (this week's most-viewed). Real GTA 6 news only; one topic per video;
  never a topic already in `workspace/explainers/*.json`.
- 6-8 sections, 550-750 words. Audience: GTA fans aged 16-30. Hook in sentence one, short spoken sentences,
  one idea per section, a question for the comments and a subscribe ask at the end.
- Original commentary in your own words. Attribute ("Rockstar confirmed", "according to previews"); mark rumors
  as rumors; say only what the source transcripts support; no profanity.
- Spell numbers as words. `explain` refuses scripts with digits, wrong length, or unprepared videos and says why.

## 6. Narrated video: footage and look

- `broll` ranges: 60-150 s where that topic is discussed **and game footage is on screen**. If a source shows
  another game or mostly a webcam, take footage from another prepared GTA 6 video and keep the original in `sources`.
- Automatic: 5 s cuts; text cards, black frames and webcam faces are skipped; voice `am_michael` at speed 1.05,
  synthesized per sentence; title card, sliding yellow headings with a red bar, channel tag top-right, footage
  credit bottom-right, subscribe card. Do not change fonts/colours per video: consistency is the brand.
- After building, open `final.sheet.jpg`. Wrong game, a face, or broken frames -> fix the ranges and rebuild.

## 7. Thumbnails

Pick the candidate with real game footage (character, car, city). Never a real person's photo, a tweet, or a
text-heavy screenshot. Headline 2-3 words in caps. Shorts thumbnails cannot be set by API.

## 8. When something breaks

| Symptom | Cause / fix |
|---|---|
| "another clipper run is still going" | a run is active; wait. Stale python processes: kill them, the lock frees itself |
| `ModuleNotFoundError` | use `.venv\Scripts\python.exe`, not system Python |
| ffmpeg not found | refresh PATH (see task files) |
| voice-over "looks garbled" | rephrase that section into shorter sentences and rebuild |
| "hi-res B-roll failed" | YouTube throttled; the low-bitrate copy was used. Rebuild later for full quality |
| "thumbnail refused" | custom thumbnails not enabled: youtube.com/features |
| "stats need read access" | run `python -m clipper auth` again |
| Whisper crash on exit | harmless; transcript is saved, the retry picks it up |
| Do not upgrade | `ctranslate2==4.5.0`, `onnxruntime-gpu==1.19.2`; install `kokoro-onnx` with `--no-deps` |

## 9. Changing the pipeline

Change code, run `ruff check .` and `pytest -q`, update this file and `docs/tasks/*.md` in the same commit, push.
The scheduled tasks read `docs/tasks/*.md` at run time, so the repo is the single source of truth.
