"""Central settings. Override any value via .env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name, default):
    return os.environ.get(name, default)


# --- keep the PC responsive: GPU does the heavy work, CPU is capped and low priority ---
CPU_THREADS = int(_env("CPU_THREADS", "3"))  # max CPU threads any step may use (PC has 12)
USE_GPU_ENCODE = _env("USE_GPU_ENCODE", "1") == "1"  # NVENC/NVDEC instead of libx264
GPU_FILTERS = _env("GPU_FILTERS", "1") == "1"  # crop/scale/blur on the GPU via libplacebo (Vulkan)
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, str(CPU_THREADS))


def lower_priority():
    """Run this process (and the ffmpeg/python children it starts) below normal priority."""
    if os.name == "nt":
        import ctypes
        BELOW_NORMAL = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)
    else:
        os.nice(10)


lower_priority()


WORKSPACE = ROOT / _env("WORKSPACE_DIR", "workspace")
FONTS_DIR = ROOT / "fonts"
SECRETS_DIR = ROOT / "secrets"
CLIENT_SECRET_FILE = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "youtube_token.json"
COOKIES_FILE = SECRETS_DIR / "cookies.txt"
STATE_FILE = WORKSPACE / "state.json"
CHANNELS_FILE = ROOT / "channels.txt"

# Claude
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-haiku-5-5")
CLIPS_PER_VIDEO = int(_env("CLIPS_PER_VIDEO", "3"))

# Transcription
WHISPER_MODEL = _env("WHISPER_MODEL", "large-v3")  # use "small" or "medium" on CPU
WHISPER_DEVICE = _env("WHISPER_DEVICE", "auto")  # auto | cuda | cpu
WHISPER_LANGUAGE = _env("WHISPER_LANGUAGE", "") or None  # e.g. "en", "hi"; empty = autodetect

# Clip rules
MIN_CLIP_SEC = float(_env("MIN_CLIP_SEC", "25"))
MAX_CLIP_SEC = float(_env("MAX_CLIP_SEC", "75"))
HEATMAP_PEAKS = int(_env("HEATMAP_PEAKS", "8"))  # how many top moments are sent to Claude
SCENE_SIGNAL = _env("SCENE_SIGNAL", "1") == "1"  # include on-screen activity in the moment score
SIGNAL_WEIGHTS = {"heat": 0.4, "loud": 0.25, "speech": 0.15, "scene": 0.2}  # renormalised over what's available
CHANNEL_LANGUAGE = _env("CHANNEL_LANGUAGE", "en")  # videos whose speech is another language are skipped
PEAK_CONTEXT_SEC = float(_env("PEAK_CONTEXT_SEC", "45"))  # seconds of transcript either side of a top moment
PEAK_MIN_GAP_SEC = float(_env("PEAK_MIN_GAP_SEC", "75"))  # top moments must be at least this far apart
WINDOW_BUDGET_SEC = float(_env("WINDOW_BUDGET_SEC", "420"))  # max total transcript time sent (token cap)
# When a video has no heatmap, only this many minutes of transcript are sent (token cap).
NO_HEATMAP_MAX_MIN = float(_env("NO_HEATMAP_MAX_MIN", "30"))

# Render
OUT_W, OUT_H = 1080, 1920
MAX_SOURCE_HEIGHT = int(_env("MAX_SOURCE_HEIGHT", "2160"))  # per-clip hi-res re-download (0 = off)
OUT_FPS = _env("OUT_FPS", "auto")  # auto = keep source fps up to 60; or a number
FRAMING = _env("FRAMING", "auto")  # auto | face | center | blur  (see reframe.py)
CAPTION_FONT = _env("CAPTION_FONT", "Montserrat ExtraBold")
CAPTION_WORDS_PER_LINE = int(_env("CAPTION_WORDS_PER_LINE", "3"))
CREDIT_TEXT = _env("CREDIT_TEXT", "Credit: {channel}")  # shown at top of every clip
CRF = _env("CRF", "20")

# Upload
PRIVACY = _env("PRIVACY", "private")  # private | unlisted | public
DAILY_UPLOAD_LIMIT = int(_env("DAILY_UPLOAD_LIMIT", "6"))  # 10k quota / 1600 per upload
REVIEW_BEFORE_UPLOAD = _env("REVIEW_BEFORE_UPLOAD", "1") == "1"  # clips wait for `approve` before uploading
MIN_UPLOAD_GAP_MIN = int(_env("MIN_UPLOAD_GAP_MIN", "180"))  # spread uploads through the day, not in a burst
MAX_UPLOADS_PER_RUN = int(_env("MAX_UPLOADS_PER_RUN", "2"))
CATEGORY_ID = _env("CATEGORY_ID", "24")  # 24 Entertainment, 22 People & Blogs, 20 Gaming

for d in (WORKSPACE, FONTS_DIR, SECRETS_DIR):
    d.mkdir(parents=True, exist_ok=True)
