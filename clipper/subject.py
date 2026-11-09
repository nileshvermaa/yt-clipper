"""Pretrained object detector (YOLOX-S, COCO classes) used to follow the main subject in gameplay.

Faces are useless for game footage (back-of-head characters, NPC faces), so for non-talking-head
clips the crop follows the most prominent person/vehicle/aircraft/boat instead. Runs on the GPU
through onnxruntime-gpu (~10 ms/frame); falls back to the CPU provider automatically.
"""
from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parent.parent / "models" / "yolox.onnx"
SIZE = 640
# COCO id -> how much we like it as "the thing the shot is about"
CLASSES = {0: 1.0, 1: 0.6, 2: 1.0, 3: 0.9, 4: 1.0, 5: 0.8, 7: 0.8, 8: 1.0}  # person, bike, car, moto, plane, bus, truck, boat
_session = None
_grid = None


def available():
    return MODEL.exists()


def _get_session():
    global _session
    if _session is None:
        from . import transcribe
        transcribe._add_cuda_dlls()
        import onnxruntime as ort
        _session = ort.InferenceSession(str(MODEL), providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    return _session


def _grids():
    global _grid
    if _grid is None:
        gs, ss = [], []
        for s in (8, 16, 32):
            n = SIZE // s
            yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
            gs.append(np.stack((xv, yv), 2).reshape(-1, 2))
            ss.append(np.full((n * n, 1), s))
        _grid = (np.concatenate(gs).astype(np.float32), np.concatenate(ss).astype(np.float32))
    return _grid


def detect(frame, conf=0.3):
    """Return [(cx, cy, w, h, class_id, score)] in the frame's own pixel coordinates."""
    h, w = frame.shape[:2]
    r = min(SIZE / h, SIZE / w)
    nh, nw = int(h * r), int(w * r)
    canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)
    canvas[:nh, :nw] = cv2.resize(frame, (nw, nh))
    blob = canvas.transpose(2, 0, 1)[None].astype(np.float32)
    out = _get_session().run(None, {"images": blob})[0][0]  # (8400, 85)

    grid, stride = _grids()
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(out[:, 2:4]) * stride
    cls_scores = out[:, 4:5] * out[:, 5:]
    cls = cls_scores.argmax(1)
    score = cls_scores.max(1)
    keep = (score > conf) & np.isin(cls, list(CLASSES))
    if not keep.any():
        return []
    xy, wh, cls, score = xy[keep], wh[keep], cls[keep], score[keep]
    boxes = np.concatenate([xy - wh / 2, wh], 1) / r  # x, y, w, h in source pixels
    idx = cv2.dnn.NMSBoxes(boxes.tolist(), score.tolist(), conf, 0.45)
    res = []
    for i in np.array(idx).reshape(-1):
        x, y, bw, bh = boxes[i]
        res.append((x + bw / 2, y + bh / 2, bw, bh, int(cls[i]), float(score[i])))
    return res


def pick(dets, W, H, prev_cx=None):
    """Choose the main subject: big, near the middle, and close to where we were last frame."""
    best, best_s = None, 0.0
    for cx, cy, bw, bh, c, sc in dets:
        area = (bw * bh) / (W * H)
        s = (area ** 0.5) * CLASSES[c] * sc
        s *= np.exp(-(((cx / W) - 0.5) / 0.4) ** 2)  # prefer centre of frame
        if prev_cx is not None:
            s *= 0.3 + 0.7 * np.exp(-(((cx - prev_cx) / W) / 0.2) ** 2)  # stay on the same subject
        if s > best_s:
            best, best_s = cx, s
    return best
