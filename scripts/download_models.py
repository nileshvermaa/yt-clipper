"""Download the two pretrained ONNX models into models/ (they are not stored in git)."""
import urllib.request
from pathlib import Path

MODELS = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "yolox.onnx": "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
    "tts/kokoro-v1.0.onnx":
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "tts/voices-v1.0.bin":
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}

out = Path(__file__).resolve().parent.parent / "models"
out.mkdir(exist_ok=True)
for name, url in MODELS.items():
    dst = out / name
    if dst.exists():
        print(f"ok        {name}")
        continue
    print(f"download  {name}")
    dst.parent.mkdir(exist_ok=True)
    urllib.request.urlretrieve(url, dst)
