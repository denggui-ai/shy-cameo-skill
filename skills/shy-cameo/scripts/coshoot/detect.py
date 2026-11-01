"""Optional OpenCV face detector. Without OpenCV callers degrade to prompts."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

Box = Tuple[int, int, int, int]  # x, y, w, h


class Detector:
    def faces(self, path: Path) -> List[Box]:
        raise NotImplementedError

    def blur(self, path: Path) -> float:
        raise NotImplementedError


class OpenCVDetector(Detector):
    def __init__(self):
        import cv2  # optional dependency
        if not hasattr(cv2, "CascadeClassifier"):
            # OpenCV 5 removed Haar cascades; treat it as unavailable.
            raise ImportError("OpenCV build without CascadeClassifier (need opencv 4.x)")
        self._cv2 = cv2
        self._cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def _gray(self, path: Path):
        img = self._cv2.imread(str(path))
        if img is None:
            raise ValueError(f"cannot read image: {path}")
        return self._cv2.cvtColor(img, self._cv2.COLOR_BGR2GRAY)

    def faces(self, path: Path) -> List[Box]:
        found = self._cascade.detectMultiScale(self._gray(path), scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return [tuple(int(v) for v in box) for box in found]

    def blur(self, path: Path) -> float:
        return float(self._cv2.Laplacian(self._gray(path), self._cv2.CV_64F).var())


def default_detector() -> Optional[Detector]:
    try:
        return OpenCVDetector()
    except Exception:  # broken installs (e.g. missing cv2.data) must degrade too
        return None
