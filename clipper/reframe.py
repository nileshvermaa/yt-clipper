"""Stage 4: find the speaker's horizontal position and produce a smooth 9:16 crop path.

Samples ~3 frames/sec (cheap), detects faces, picks the most prominent face near the
previous position (stable tracking), smooths with EMA, and writes an FFmpeg sendcmd
file that pans the crop window over time.
"""
from pathlib import Path

import cv2

cv2.setNumThreads(2)
SAMPLE_FPS = 2  # fewer detections = less CPU; the EMA smoothing hides the lower rate
ALPHA = 0.15  # EMA smoothing; lower = steadier camera
DEADZONE = 0.04  # ignore moves smaller than 4% of frame width
CUT_THRESHOLD = 30  # mean 0-255 pixel change between sampled frames (0.5 s apart) that counts as a hard cut


YUNET = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
DETECT_W = 640  # detect on a downscaled frame for speed


def _detector():
    if YUNET.exists():
        det = cv2.FaceDetectorYN.create(str(YUNET), "", (DETECT_W, DETECT_W), 0.6)

        def run(frame):
            h, w = frame.shape[:2]
            s = DETECT_W / w
            small = cv2.resize(frame, (DETECT_W, int(h * s)))
            det.setInputSize((small.shape[1], small.shape[0]))
            _, faces = det.detect(small)
            if faces is None:
                return []
            return [((f[0] + f[2] / 2) / s, f[2] * f[3] / s / s) for f in faces]
        return run
    else:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def run(frame):
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return [(x + w / 2, w * h) for x, y, w, h in cascade.detectMultiScale(g, 1.1, 6, minSize=(60, 60))]
        return run


def _sample_frames(source, start, end, W, H):
    """Yield small BGR frames at SAMPLE_FPS from one ffmpeg pass.

    Fast path: NVDEC decodes and scale_cuda shrinks on the GPU, so only tiny frames cross to the CPU.
    If that path fails (unusual pixel format etc.) it falls back to a CPU downscale.
    """
    import subprocess

    import numpy as np
    sh = max(2, int(H * DETECT_W / W) // 2 * 2)
    n = DETECT_W * sh * 3
    seek = ["-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(source)]
    out = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    paths = [
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", *seek,
         "-vf", f"fps={SAMPLE_FPS},scale_cuda={DETECT_W}:{sh}:format=nv12,hwdownload,format=nv12", *out],
        ["-hwaccel", "cuda", *seek, "-vf", f"fps={SAMPLE_FPS},scale={DETECT_W}:{sh}", *out],
    ]
    for args in paths:
        p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "2", *args],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        got = 0
        try:
            while len(buf := p.stdout.read(n)) == n:
                got += 1
                yield np.frombuffer(buf, np.uint8).reshape(sh, DETECT_W, 3).copy()
        finally:
            p.stdout.close()
            p.wait()
        if got:
            return


def sample(source, start, end):
    """(frames, W, H): the small sampled frames of [start, end], shared by every analysis step."""
    cap = cv2.VideoCapture(str(source))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return list(_sample_frames(source, start, end, W, H)), W, H


FACE_MIN_AREA = 0.012  # a "talking head" face fills >1.2% of the frame; smaller ones are crowd/NPCs


def detect_reaction(source, start, end, frames=None, size=None):
    """Detect a screen-recorded commentary video: a small, stationary facecam in a side/top corner.

    Returns None, or a layout dict in `source` pixels: the facecam box, the main-content box (the
    screen minus the facecam column and the taskbar) and the output geometry for a stacked 9:16
    (content on top, facecam below). Talking-head videos have a big face, so they never match.
    `frames`/`size` = the shared output of sample(), to avoid decoding the clip twice.
    """
    import numpy as np
    from . import config
    if config.FRAMING not in ("auto", "reaction") or not YUNET.exists():
        return None
    if frames is None:
        frames, W, H = sample(source, start, min(end, start + 10))
    else:
        W, H = size
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (DETECT_W, DETECT_W), 0.6)
    k = W / DETECT_W
    boxes, n = [], 0
    for small in frames[: int(SAMPLE_FPS * 10) : 2]:  # first 10 s, every other sample: plenty for a static facecam
        n += 1
        fh, fw = small.shape[:2]
        det.setInputSize((fw, fh))
        _, faces = det.detect(small)
        best = None
        for f in (faces if faces is not None else []):
            x, y, w, h = f[:4]
            area, cx, cy = w * h / (fw * fh), (x + w / 2) / fw, (y + h / 2) / fh
            if 0.002 <= area <= 0.04 and (cx < 0.3 or cx > 0.7) and cy < 0.65 and (best is None or area > best[0]):
                best = (area, x * k, y * k, w * k, h * k)
        if best:
            boxes.append(best[1:])
    if n < 4 or len(boxes) < max(3, 0.6 * n):
        return None
    b = np.array(boxes)
    cx, cy = b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2
    if cx.std() > 0.02 * W or cy.std() > 0.03 * H:  # a facecam doesn't move
        return None
    fx, fy, fw_, fh_ = np.median(b, axis=0)
    fcx, fcy = fx + fw_ / 2, fy + fh_ / 2

    # facecam box: the detector box is tight; the camera frame is roughly a square ~3.3x the face width
    cw = ch = min(fw_ * 3.3, 0.3 * W, 0.5 * H)
    cam_x = int(min(max(fcx - cw / 2, 0), W - cw)) // 2 * 2
    cam_y = int(min(max(fcy - ch / 2, 0), H - ch)) // 2 * 2
    cam_w, cam_h = int(cw) // 2 * 2, int(ch) // 2 * 2

    # Snap to the camera's coloured border when there is one (streamers usually outline the facecam).
    cap = cv2.VideoCapture(str(source))
    cap.set(cv2.CAP_PROP_POS_MSEC, (start + 1.0) * 1000)
    ok, frame = cap.read()
    cap.release()
    if ok:
        pad = int(0.5 * cam_w)
        x0, y0 = max(0, cam_x - pad), max(0, cam_y - pad)
        x1, y1 = min(W, cam_x + cam_w + pad), min(H, cam_y + cam_h + pad)
        roi = frame[y0:y1, x0:x1].astype(int)
        mask = (roi[..., 2] > 170) & (roi[..., 1] < 80) & (roi[..., 0] < 80)  # strong red (BGR)
        # only long red lines count as border edges (red chat usernames are short and scattered)
        need = 0.6 * min(cam_w, cam_h)
        rows = np.nonzero(mask.sum(axis=1) > need)[0]
        cols = np.nonzero(mask.sum(axis=0) > need)[0]
        if len(rows) and len(cols):
            bx0, bx1, by0, by1 = cols.min(), cols.max(), rows.min(), rows.max()
            bw, bh = bx1 - bx0, by1 - by0
            if 0.5 * cam_w <= bw <= 1.8 * cam_w and 0.5 * cam_h <= bh <= 1.8 * cam_h:
                inset = max(4, int(0.012 * W))  # skip the border line itself
                cam_x, cam_y = (x0 + bx0 + inset) // 2 * 2, (y0 + by0 + inset) // 2 * 2
                cam_w, cam_h = (bw - 2 * inset) // 2 * 2, (bh - 2 * inset) // 2 * 2
    cam_x, cam_y, cam_w, cam_h = int(cam_x), int(cam_y), int(cam_w), int(cam_h)

    # main content: everything beside the facecam column, minus the taskbar strip at the bottom
    if fcx < W / 2:
        ct_x = int(min(cam_x + cam_w + 0.04 * W, 0.35 * W)) // 2 * 2
        ct_w = (W - ct_x) // 2 * 2
    else:
        ct_x = 0
        ct_w = int(max(cam_x - 0.04 * W, 0.65 * W)) // 2 * 2
    ct_h = int(H * 0.96) // 2 * 2

    # output geometry on the 1080x1920 canvas
    ow = config.OUT_W
    out_ct_h = int(round(ow * ct_h / ct_w)) // 2 * 2
    out_fc_w = 700
    out_fc_h = int(round(out_fc_w * cam_h / cam_w)) // 2 * 2
    gap = 30
    total = out_ct_h + gap + out_fc_h
    y1 = (config.OUT_H - total) // 2
    return {
        "W": W, "H": H,
        "content": (ct_x, 0, ct_w, ct_h), "cam": (cam_x, cam_y, cam_w, cam_h),
        "out_content": (0, y1, ow, out_ct_h),
        "out_cam": ((ow - out_fc_w) // 2, y1 + out_ct_h + gap, out_fc_w, out_fc_h),
        "cap_y": y1 + out_ct_h + gap // 2,  # captions sit on the seam between the two panels
    }


def crop_path(source, start, end, mode=None, frames=None, size=None):
    """Return (crop_w, [(t_rel, x_left), ...], W, mode_used) in `source` pixels.

    mode 'auto' picks per clip: big faces in most frames -> follow the face (talking head);
    otherwise follow the main person/vehicle (gameplay); otherwise a plain centre crop.
    `frames`/`size` = the shared output of sample(), to avoid decoding the clip twice.
    """
    import numpy as np
    from . import config, subject
    mode = mode or config.FRAMING
    if frames is None:
        frames, W, H = sample(source, start, end)
    else:
        W, H = size
    crop_w = min(W, int(H * 9 / 16)) // 2 * 2
    center = [(0.0, (W - crop_w) // 2)]
    if mode == "center" or not frames:
        return crop_w, center, W, "center"

    detect_face = _detector()
    use_obj = subject.available() and mode in ("auto", "object")
    k = W / DETECT_W
    n = len(frames)
    cuts, objs_per = [], []
    prev_g = None
    for small in frames:
        # scene cut = big jump between consecutive sampled frames (tiny grayscale thumbnails, essentially free)
        g = cv2.resize(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (64, 36)).astype(np.int16)
        cuts.append(prev_g is not None and float(np.abs(g - prev_g).mean()) > CUT_THRESHOLD)
        prev_g = g
        objs_per.append([(cx * k, cy, bw * k, bh * k, c, s) for cx, cy, bw, bh, c, s in subject.detect(small)] if use_obj else [])

    # Faces only matter for talking-head clips: judge that on every 3rd frame, and run the (CPU) face
    # detector on the rest only if the clip really is a talking head.
    faces_per = [None] * n

    def faces_at(i):
        if faces_per[i] is None:
            fh = frames[i].shape[0]
            faces_per[i] = [(x * k, a / (DETECT_W * fh)) for x, a in detect_face(frames[i])]
        return faces_per[i]

    probe = range(0, n, 3)
    face_share = sum(1 for i in probe if any(f[1] >= FACE_MIN_AREA for f in faces_at(i))) / len(probe)
    obj_share = sum(1 for o in objs_per if o) / n
    if mode == "face" or (mode == "auto" and face_share >= 0.5):
        used = "face"
        for i in range(n):
            faces_at(i)
    elif use_obj and obj_share >= 0.3:
        used = "object"
    else:
        return crop_w, center, W, "center"

    raw, prev = [], None
    for i in range(n):
        cx = None
        if used == "face":
            cands = faces_per[i] if mode == "face" else [f for f in faces_per[i] if f[1] >= FACE_MIN_AREA]
            if cands:
                # prefer large faces, penalise jumping across the frame (keeps lock on one speaker)
                ref = prev if prev is not None else W / 2
                cx = max(cands, key=lambda f: f[1] / (1 + abs(f[0] - ref) / W * 3))[0]
        else:
            cx = subject.pick([(c[0], c[1] * k, c[2], c[3], c[4], c[5]) for c in objs_per[i]], W, H, prev)
        if cx is not None:
            prev = cx
        raw.append((i / SAMPLE_FPS, cx))

    found = [c for _, c in raw if c is not None]
    path, smooth, last_x = [], found[0], None
    for (tr, c), cut in zip(raw, cuts):
        target = c if c is not None else smooth
        jump = cut and c is not None  # new shot: snap to the new subject instead of panning across the cut
        if jump:
            smooth = target
        elif abs(target - smooth) > DEADZONE * W:
            smooth = ALPHA * target + (1 - ALPHA) * smooth
        x = int(min(max(smooth - crop_w / 2, 0), W - crop_w))
        if jump and last_x is not None and x != last_x:
            path.append((round(max(tr - 0.04, 0), 2), last_x))  # hold the old position up to the cut
            path.append((round(tr, 2), x))
            last_x = x
        elif last_x is None or abs(x - last_x) >= 2:
            path.append((round(tr, 2), x))
            last_x = x
    return crop_w, path, W, used


def write_sendcmd(path, file, scale=1.0):
    """Crop-x keyframes for ffmpeg's sendcmd; `scale` converts analysis pixels to render pixels."""
    with open(file, "w", encoding="utf-8") as f:
        for t, x in path:
            f.write(f"{t:.2f} crop x {int(round(x * scale))};\n")
