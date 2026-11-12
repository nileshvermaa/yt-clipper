# YouTube Shorts Clipper – Setup

The pipeline: **yt-dlp** downloads the video and its heatmap → **faster-whisper** transcribes it locally (free) → **Claude Haiku** picks 3 clips (one call, ~3–5k tokens, under 1¢) → **OpenCV/MediaPipe** follows the speaker's face → **FFmpeg + libass** renders a 9:16 video with karaoke captions, a title card and a credit line → **YouTube Data API** uploads it.

## Services and API keys you need

| Service | What it's for | Cost | Where |
|---|---|---|---|
| **Anthropic API** | Picks the clips | Pay-as-you-go, ~$0.005/video | console.anthropic.com → API Keys |
| **Google Cloud project + YouTube Data API v3** | Uploading | Free (10,000 quota/day ≈ 6 uploads) | console.cloud.google.com |
| YouTube channel | Where the Shorts go | Free | youtube.com |

No other connectors are needed. yt-dlp, Whisper, OpenCV and FFmpeg all run on your PC.

## Manual steps (once)

### 1. Install the tools (Windows)
```bash
winget install Python.Python.3.12
```
```bash
winget install Gyan.FFmpeg
```
Open a new terminal afterwards so `ffmpeg` and `python` are on PATH.

**GPU (optional, much faster):** with an NVIDIA card, install the CUDA 12 runtime and cuDNN 9 so faster-whisper can use it. With no GPU, set `WHISPER_MODEL=small` in `.env`.

### 2. Install the Python packages
```bash
python -m venv .venv
```
```bash
.venv\Scripts\activate
```
```bash
pip install -r requirements.txt
```

Face tracking uses OpenCV's YuNet model at `models/face_detection_yunet_2023mar.onnx` (from github.com/opencv/opencv_zoo). If that file is missing, it falls back to the older Haar detector. `ctranslate2` is pinned to 4.5.0 because 4.8.x crashes on load on this PC.

### 3. Anthropic key
1. console.anthropic.com → Billing: add about $5 credit.
2. API Keys → Create key.
3. `copy .env.example .env` and paste the key into `ANTHROPIC_API_KEY`.

### 4. YouTube upload credentials (the longest step)
1. Go to console.cloud.google.com and create a project (for example "shorts-clipper").
2. APIs & Services → Library → **YouTube Data API v3** → Enable.
3. APIs & Services → **OAuth consent screen**:
   - User type: External. Fill in the app name and your email.
   - Scopes: add `.../auth/youtube.upload`.
   - **Test users: add the Google account that owns your YouTube channel.**
   - Then **Publish app** ("In production"). If you leave it in Testing, the refresh token expires every 7 days. You don't need Google verification for personal use; you'll just see an "unverified app" warning once.
4. APIs & Services → Credentials → Create credentials → **OAuth client ID** → type **Desktop app** → Download JSON. Save it as `secrets/client_secret.json`.
5. Run:
   ```bash
   python -m clipper auth
   ```
   A browser opens. Pick the account or **brand account** that owns the channel, accept the "unverified app" warning (Advanced → Go to …), and allow access. This creates `secrets/youtube_token.json`.

**Important:** uploads from an unverified API project are often locked to **private** by YouTube. To make them public, either complete the **YouTube API Services audit** (Google form "YouTube API Services – Audit and Quota Extension"; takes days to weeks) or upload as private and switch them to public by hand in YouTube Studio. The default here is `PRIVACY=private` so you can review clips anyway.

### 5. Channel prep on YouTube
- Verify your phone number at youtube.com/verify. This unlocks custom thumbnails and longer uploads, and lowers spam flags.
- Upload one video manually first so the channel exists and is set up.

### 6. Fonts
Download **Montserrat** from fonts.google.com/specimen/Montserrat and copy `Montserrat-ExtraBold.ttf` into `fonts/`. Without it, libass uses a fallback font.

### 7. Cookies (only if downloads fail with "Sign in to confirm you're not a bot")
Running from a home PC usually works without this. If not, install the "Get cookies.txt LOCALLY" browser extension, open youtube.com while logged in, export, and save as `secrets/cookies.txt`. Use a spare Google account, not your main one.

### 8. Permission to clip
Only clip creators who allow it (open clipping programs, written permission, or your own content). Keep screenshots of the permission. Every clip already gets a title card, captions, a credit line and a link to the original. Content ID may still claim clips; that's normal for clip channels and usually just shares the revenue.

## Daily use
```bash
python -m clipper run "https://www.youtube.com/watch?v=VIDEO_ID"
```
This creates `workspace/<id>/clip1/short.mp4` and so on. Watch them, delete a clip folder's `short.mp4` and set its status in `clips.json` if you want to drop it, then:
```bash
python -m clipper upload-pending
```
```bash
python -m clipper status
```

Automatic mode: list channels in `channels.txt`, then run
```bash
python -m clipper watch --upload
```
To run it automatically, create a Windows Task Scheduler task every 6 hours with program `G:\gta6\.venv\Scripts\python.exe`, arguments `-m clipper watch --upload`, and "Start in" `G:\gta6`. The quota guard stops after 6 uploads per day; the rest wait for the next run.

## Re-running and tuning
Each stage caches its output in `workspace/<id>/` (`transcript.json`, `clips.json`, `clipN/`). Delete a file to redo that stage. For example, delete `clips.json` to get new picks (costs one more Claude call), or a `clipN` folder to re-render.

| Problem | Fix |
|---|---|
| Clips too long or short | `MIN_CLIP_SEC` / `MAX_CLIP_SEC` |
| Camera follows the wrong person | Lower `ALPHA` in `reframe.py`, or edit `crop.cmd` and re-render |
| Whisper too slow on CPU | `WHISPER_MODEL=small` |
| Non-English | `WHISPER_LANGUAGE=hi` etc.; titles follow the transcript's language |
| Need more than 6 uploads a day | Quota extension request (same Google audit form) |

## Framing and quality (how the crop is chosen)
Each clip is analysed on the 1080p copy and rendered from the best stream YouTube offers (up to 4K), so the 9:16 crop stays sharp.
- **auto** (default): big faces in most frames -> follows the face (talking heads); otherwise follows the main person, car, plane or boat using a pretrained YOLOX detector on your GPU (`models/yolox.onnx`); otherwise a plain centre crop.
- **blur**: shows the whole 16:9 picture centred on a blurred copy of itself, so nothing is cropped out. Set `FRAMING=blur` in `.env`.
- Set `FRAMING=center` for a fixed centre crop, or `MAX_SOURCE_HEIGHT=0` to skip the 4K stream.
- Each render prints which framing and source it used, e.g. `framing=object source=stream 2160p 30fps`.

## "Versus" Shorts (two videos back to back, like GTA V then GTA VI)
```bash
.venv\Scripts\python.exe -m clipper versus --a "<GTA V video url>" 1:12 1:32 --b "<GTA 6 video url>" 11:36 11:56 --label-a "GTA V" --label-b "GTA VI"
```
Each half gets the same tracked 9:16 framing from the 4K stream, a text label on top and a "Footage: <channel>" credit, then the two are joined. Output: `workspace\versus\<labels>\versus.mp4`. Review it, then add `--upload --title "GTA 6 vs GTA 5: Escaping the Cops"` to publish (private by default, counts as one upload).
- Times are seconds or `m:ss`; about 20 seconds per half works well.
- Use `--logo-a logo_v.png --logo-b logo_vi.png` to show your own PNG logos instead of the text labels (no logos are included).

## Screen-recorded commentary videos ("reaction" layout)
If a video is a desktop recording with a small stationary facecam in a corner (typical streamer commentary), `FRAMING=auto` switches to a stacked layout: the main content (browser/game window, without the facecam column or taskbar) on top, the facecam below it (snapped to its coloured border when there is one), a blurred backdrop, and the captions on the seam between the two. Talking-head and gameplay videos don't match and keep their normal framing. Render output shows `framing=reaction`.
Every render is checked for completeness (video and audio must both reach the full length); a truncated network read is retried, then falls back to the local 1080p copy.

## GPU pipeline and CPU cost (Phase 1)
Render order, lowest CPU first; each step falls back to the next if it fails:
1. **Vulkan**: 4K AV1 stream decoded on the GPU, cropped and scaled by libplacebo on the GPU, only the finished 1080x1920 picture reaches the CPU.
2. **NVDEC + libplacebo**: 4K VP9 decoded on the GPU, frames pass through system memory.
3. **NVDEC + CPU filters**, then the local 1080p copy. A transient YouTube 403 triggers one retry with fresh links before falling back.
Tracking decodes and downsizes its sample frames on the GPU, shares them between the layout checks, and only runs the CPU face detector when the clip looks like a talking head. Hard scene cuts make the crop jump to the new subject instead of panning across the cut. Network reads auto-reconnect and every render is checked for full video and audio length.

Measured on this PC (CPU-seconds used by the pipeline, lower is better):
| Clip | Before | Now |
|---|---|---|
| 30 s gameplay, 4K | 9.6 | 5.6 |
| 65 s commentary (stacked layout), 4K 60 fps | 93.9 | 27.7 |
Set `GPU_FILTERS=0` in `.env` to force the old CPU filters.

## Picking moments (Phase 2: free scoring, no extra AI cost)
Before Claude sees anything, every 5-second slice of the video is scored from free signals: YouTube's Most Replayed curve (when it exists), loudness spikes, speaking rate and on-screen activity (about 20 s per video, almost no CPU). Only the top moments plus ~45 s around each go into `candidates.txt`, and each window is labelled with its score and why (`score 2.5: loud+scene+speech`), capped at `WINDOW_BUDGET_SEC` of transcript. On a 22-minute video that sends about 35% of the transcript (1.9k tokens instead of 5.3k); short videos send nearly all of it. Works for gameplay with no commentary too.
Caption guard: YouTube auto-captions that look like garbage (one word making up over 6% of the text, loops of repeats) are replaced by a Whisper transcript. Whisper also detects the spoken language first; if it is not `CHANNEL_LANGUAGE`, the video is skipped in seconds (`skipped.txt` says why) instead of being transcribed.
Not built, on purpose: trimming pauses inside clips. In our content the long pauses are mostly the creator watching a video that is playing on screen, so cutting them removes the content.

## Phase 4: quality gate before upload

`finish` now renders, runs free checks (missing file, silent audio, overlap with an earlier clip) and writes a
6-frame contact sheet next to each clip (`short.sheet.jpg`). Clips then wait in status `review`.

```
python -m clipper review                      # list sheets waiting for a look
python -m clipper approve <video_id> 1 2      # or --all
python -m clipper reject  <video_id> 3 -r "text cut off"
```

Only `approved` clips upload. Uploads are paced: at most `MAX_UPLOADS_PER_RUN` (2) per run and
and a run does nothing if the previous run uploaded less than `MIN_UPLOAD_GAP_MIN` (180) minutes ago. Set `REVIEW_BEFORE_UPLOAD=0` for the old behaviour.
Every step is logged in `workspace/<id>/log.txt`.

## Weekly long-form compilation (16:9)

```
python -m clipper compile                  # best approved/uploaded clips of the last 7 days -> ~10 min video + sheet
python -m clipper compile --approve 2026-11-09
python -m clipper compile --upload         # uploads approved compilations (Private, chapters + credits in description)
```

Cut from the local 1080p copies (NVENC, loudness -14 LUFS), max 2 segments per source video, clips are never
reused in a later compilation. Output: `workspace/compilations/<date>.mp4/.json/.sheet.jpg`.

## Analytics feedback loop

`python -m clipper stats` pulls views, likes and privacy for every uploaded video (Data API, 1 quota unit per
50 videos) and retention / subscribers gained (YouTube Analytics API, separate free quota). Once at least 8
**public** Shorts are 2+ days old it writes `workspace/insights.txt`: best and weakest source channels, which
clip length holds viewers, and the titles that worked or flopped. Every new `candidates.txt` includes it, so
clip picking learns from your own channel. Private videos have no views, so nothing is learned until you
publish.

One-time setup:
1. Google Cloud console > APIs & Services > Library: enable **YouTube Analytics API** (Data API v3 is already on).
2. OAuth consent screen > Data access: add scopes `youtube.readonly` and `yt-analytics.readonly`.
3. Run `python -m clipper auth` again and accept. Uploads keep working with the old token until you do.

## Custom thumbnails (weekly compilation)

`compile` also writes three candidate thumbnails, `workspace/compilations/<date>.thumb.1-3.jpg`: the best frames
from different segments (colourful, a big person or vehicle in frame, no text cards), with "GTA 6 / ALL NEW
INFO / THIS WEEK" in bold Impact. Choose one when approving: `compile --approve <date> --pick 2`; it is set right
after upload. To set or change it on an already uploaded video: `compile --thumb <date> --pick <n>` (50 quota units).

Custom thumbnails need a phone-verified channel: https://www.youtube.com/verify. Shorts thumbnails cannot be set
through the API; pick a frame in the YouTube mobile app instead.


## Narrated explainer videos (your own voice-over style)

`python -m clipper explain workspace/explainers/<name>.json` renders a 16:9 1440p video from a script:
a Kokoro TTS voice-over (local, free, voice `am_michael` every time for a consistent channel sound), B-roll cut
from the downloaded source videos into 5 s shots (text cards, black frames and creators' webcam faces are skipped
automatically), and the channel branding: animated "GTA 6" title card, sliding yellow section headings with a red
bar, the channel name top-right, a footage credit bottom-right, and a "SUBSCRIBE" card at the end. Output:
`workspace/explainers/<name>/final.mp4`, a contact sheet and 3 candidate thumbnails. Upload after review with
`--upload --pick N` (Private, chapters + source credits in the description, custom thumbnail).

Script format (Claude writes it in the app from the source transcripts; narration in its own words):

```json
{"title": "...", "thumb": {"top": "GTA 6", "headline": "30 FPS ONLY!?", "badge": "BEFORE LAUNCH"},
 "description": "...", "tags": ["..."], "sources": ["<video id whose reporting is used>"],
 "sections": [{"heading": "...", "text": "narration", "broll": [["<video id>", start_sec, end_sec]]}]}
```
