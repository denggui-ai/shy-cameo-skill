"""Optional face-likeness score (OpenCV YuNet + SFace). Advisory only: the user judges likeness.

Models are not bundled; see references/face-likeness.md. Missing OpenCV or models -> "unavailable".
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Optional

MODELS_ENV = "SHY_CAMEO_FACE_MODELS"
MODEL_SHA256 = {
    "yunet.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "sface.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}
# Provisional (2026-10-25, 26 shots of one user): covers the user rejected scored 0.71-0.82,
# the close-up judged barely alike 0.86. Recalibrate as more user verdicts arrive.
LOW_THRESHOLD = 0.83


def models_dir(ws: Optional[Path]) -> Optional[Path]:
    env = os.environ.get(MODELS_ENV)
    if env:
        return Path(env)
    return Path(ws) / "cache" / "face-models" if ws else None


def _verified(directory: Optional[Path]) -> Optional[dict]:
    if not directory:
        return None
    paths = {}
    for name, digest in MODEL_SHA256.items():
        p = directory / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            return None
        paths[name] = p
    return paths


def _unavailable(message: str) -> dict:
    return {"status": "unavailable", "score": None, "threshold": LOW_THRESHOLD, "message": message}


def score(photos: Iterable[Path], image: Path, ws: Optional[Path] = None) -> dict:
    """Best cosine similarity between the image's most confident face and any user photo. Never raises."""
    try:
        paths = _verified(models_dir(ws))
    except OSError as exc:
        return _unavailable(f"读取比脸模型失败：{exc}")
    if paths is None:
        return _unavailable("没有可用的比脸模型（缺文件或哈希不符），未做机器比脸")
    try:
        import cv2  # optional dependency
        recognizer = cv2.FaceRecognizerSF.create(str(paths["sface.onnx"]), "")

        def feature(path: Path):
            img = cv2.imread(str(path))
            if img is None:
                raise ValueError(f"cannot read image: {path}")
            h, w = img.shape[:2]
            detector = cv2.FaceDetectorYN.create(str(paths["yunet.onnx"]), "", (w, h), 0.6)
            _, faces = detector.detect(img)
            if faces is None or not len(faces):
                return None
            # Most confident, not largest: hands and bouquets can make bigger false boxes.
            face = max(faces, key=lambda f: f[-1])
            return recognizer.feature(recognizer.alignCrop(img, face))

        target = feature(Path(image))
        if target is None:
            return {"status": "no_face", "score": None, "threshold": LOW_THRESHOLD,
                    "message": "成图里没检测到脸，未做机器比脸"}
        refs = [f for f in (feature(Path(p)) for p in photos) if f is not None]
        if not refs:
            return _unavailable("本人照片里没检测到脸，未做机器比脸")
        best = max(float(recognizer.match(r, target, cv2.FaceRecognizerSF_FR_COSINE)) for r in refs)
    except Exception as exc:  # broken installs or OpenCV builds without these APIs must degrade
        return _unavailable(f"机器比脸不可用：{exc}")
    best = round(best, 3)
    if best < LOW_THRESHOLD:
        return {"status": "low", "score": best, "threshold": LOW_THRESHOLD,
                "message": f"机器比脸分 {best}，低于 {LOW_THRESHOLD}，可能不像本人；先给用户比脸，像不像以用户为准"}
    return {"status": "ok", "score": best, "threshold": LOW_THRESHOLD,
            "message": f"机器比脸分 {best}；仅供参考，像不像以用户为准"}
