"""Stage 7: YouTube Data API v3 upload with OAuth refresh token, resumable chunks, daily quota guard."""
import datetime as dt
import json
import random
import time

from . import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",       # video stats for the feedback loop
          "https://www.googleapis.com/auth/yt-analytics.readonly"]  # retention for the feedback loop


def authorize():
    """One-time browser login. Saves a refresh token to secrets/youtube_token.json."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not config.CLIENT_SECRET_FILE.exists():
        raise SystemExit(f"Missing {config.CLIENT_SECRET_FILE}. See SETUP.md step 4.")
    flow = InstalledAppFlow.from_client_secrets_file(str(config.CLIENT_SECRET_FILE), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    config.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved token to {config.TOKEN_FILE}")


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if not config.TOKEN_FILE.exists():
        raise SystemExit("Not authorized. Run: python -m clipper auth")
    # no scopes argument: refresh with whatever the saved token was granted, so an older upload-only token keeps working
    creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE))
    if not creds.valid:
        creds.refresh(Request())
        config.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def granted(scope):
    return scope in (json.loads(config.TOKEN_FILE.read_text(encoding="utf-8")).get("scopes") or [])


def _service(api="youtube", version="v3"):
    from googleapiclient.discovery import build
    return build(api, version, credentials=_creds(), cache_discovery=False)


def _state():
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return {"uploads": {}, "processed": []}


def save_state(s):
    config.STATE_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def uploads_today():
    # YouTube quota resets at midnight Pacific; UTC-8 is a close-enough approximation.
    day = (dt.datetime.utcnow() - dt.timedelta(hours=8)).date().isoformat()
    return day, _state()["uploads"].get(day, 0)


def minutes_since_last_upload():
    last = _state().get("last_upload")
    if not last:
        return None
    return (dt.datetime.utcnow() - dt.datetime.fromisoformat(last)).total_seconds() / 60


def upload(file_path, meta, clip, publish_at=None, shorts=True):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    day, count = uploads_today()
    if count >= config.DAILY_UPLOAD_LIMIT:
        raise RuntimeError(f"Daily upload limit reached ({count}). Try again after quota reset.")

    desc = (
        f"{clip['description']}\n\n"
        f"Full video: {meta['url']}\n"
        f"Credit: {meta['channel']} {meta.get('channel_url', '')}\n\n#Shorts"
    ) if shorts else clip["description"]
    status = {"privacyStatus": config.PRIVACY, "selfDeclaredMadeForKids": False}
    if publish_at:
        status = {"privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False}
    body = {
        "snippet": {
            "title": (f"{clip['title']} #Shorts" if shorts else clip["title"])[:100],
            "description": desc[:4900],
            "tags": (clip.get("tags", []) + (["Shorts", meta["channel"]] if shorts else []))[:15],
            "categoryId": config.CATEGORY_ID,
        },
        "status": status,
    }
    yt = _service()
    media = MediaFileUpload(str(file_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    resp, retry = None, 0
    while resp is None:
        try:
            st, resp = req.next_chunk()
            if st:
                print(f"    {int(st.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retry < 6:
                retry += 1
                time.sleep(2 ** retry + random.random())
            elif e.resp.status == 403 and b"quota" in e.content.lower():
                raise RuntimeError("YouTube API quota exceeded for today.") from e
            else:
                raise

    s = _state()
    s["uploads"][day] = s["uploads"].get(day, 0) + 1
    s["last_upload"] = dt.datetime.utcnow().isoformat()
    save_state(s)
    return resp["id"]


def set_thumbnail(video_id, image_path):
    """Custom thumbnail (50 quota units). Needs a phone-verified channel: youtube.com/verify."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    try:
        _service().thumbnails().set(videoId=video_id,
                                    media_body=MediaFileUpload(str(image_path), mimetype="image/jpeg")).execute()
        return True
    except HttpError as e:
        if e.resp.status == 403:
            print("  thumbnail refused: verify the channel at https://www.youtube.com/verify, then run "
                  "`python -m clipper compile --thumb <date> --pick <n>`")
            return False
        raise
