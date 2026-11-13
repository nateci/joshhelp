"""Face detection (YuNet) and face matching (SFace) using OpenCV's built-in DNN models."""
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
DETECTOR = ("face_detection_yunet_2023mar.onnx", f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx")
RECOGNIZER = ("face_recognition_sface_2021dec.onnx", f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx")

# Cosine-similarity threshold recommended by the SFace authors.
MATCH_THRESHOLD = 0.363
MAX_SIDE = 1280  # downscale big phone photos for speed


@dataclass
class Face:
    embedding: np.ndarray
    yaw: float  # nose offset from the eye midpoint, in eye-distances; ~0 facing the camera


def _model_path(name: str, url: str) -> str:
    path = MODELS_DIR / name
    if not path.exists():
        MODELS_DIR.mkdir(exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return str(path)


def ensure_models() -> None:
    _model_path(*DETECTOR)
    _model_path(*RECOGNIZER)


@lru_cache
def _detector():
    return cv2.FaceDetectorYN.create(_model_path(*DETECTOR), "", (320, 320), score_threshold=0.7)


@lru_cache
def _recognizer():
    return cv2.FaceRecognizerSF.create(_model_path(*RECOGNIZER), "")


def _shrink(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    return cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1 else img


def _yaw(row: np.ndarray) -> float:
    right_eye, left_eye, nose = row[4:6], row[6:8], row[8:10]
    axis = left_eye - right_eye
    return float(np.dot(nose - (right_eye + left_eye) / 2, axis) / np.dot(axis, axis))


def analyze(img: np.ndarray) -> Face | None:
    """Return the largest face in the image (embedding + yaw), or None if there's no face."""
    img = _shrink(img)
    det = _detector()
    det.setInputSize((img.shape[1], img.shape[0]))
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None
    row = max(faces, key=lambda f: f[2] * f[3])
    rec = _recognizer()
    return Face(rec.feature(rec.alignCrop(img, row)), _yaw(row))


def similarity(a: Face, b: Face) -> float:
    return float(_recognizer().match(a.embedding, b.embedding, cv2.FaceRecognizerSF_FR_COSINE))
