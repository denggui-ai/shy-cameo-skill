"""User photo check. Deterministic where possible; everything else is a prompt to the user."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from .detect import Detector, default_detector
from .findings import Finding, worst
from .png import image_size, png_decode_error

AUTO = "auto"
MIN_SHORT_SIDE = 512
MIN_FACE_WIDTH_RATIO = 0.15
BLUR_THRESHOLD = 60.0


@dataclass
class PhotoReport:
    path: str
    faces: Optional[int]
    findings: List[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"path": self.path, "faces": self.faces, "level": worst(self.findings),
                "findings": [f.to_dict() for f in self.findings]}


def check_photo(path: Path, detector: Union[str, Detector, None] = AUTO) -> PhotoReport:
    path = Path(path)
    report = PhotoReport(str(path), None)
    add = report.findings.append
    if not path.is_file():
        add(Finding("block", "missing_file", "找不到这张照片，请把照片放进 coshoot-workspace/input/"))
        return report
    if png_decode_error(path):
        add(Finding("block", "bad_image", "PNG像素数据损坏或无法完成本地解码校验，请提供有效原图"))
        return report
    size = image_size(path)
    if size is None:
        add(Finding("block", "unsupported_format", "只支持 PNG 或 JPEG，请先转换格式"))
        return report
    add(Finding("info", "angle_guide", "优先选择清晰、无遮挡、无明显美颜的原照；正脸便于对照，已有其他角度可一并提供。"
                                       "只有一张或只有侧脸不据此阻断；最低张数和可稳定生成的角度范围尚未验证，按现有素材评估。"))
    if min(size) < MIN_SHORT_SIDE:
        add(Finding("warn", "low_resolution", f"照片短边不足 {MIN_SHORT_SIDE} 像素，可能影响像不像你"))
    add(Finding("info", "beauty_filter_unknown", "无法自动判断是否开了美颜或滤镜；用原图会更像你，请确认"))
    det = default_detector() if detector == AUTO else detector
    if det is None:
        add(Finding("info", "detector_unavailable", "未安装可用的 opencv 4.x，人脸检测改为人工确认"))
        return report
    try:
        boxes = det.faces(path)
    except Exception:
        add(Finding("info", "detector_failed", "人脸检测失败（照片可能已损坏），改为人工确认"))
        return report
    report.faces = len(boxes)
    if not boxes:
        add(Finding("confirm", "no_face_detected", "没检测到人脸：请换一张清晰正脸照，或确认照片里确实是你"))
    elif len(boxes) > 1:
        add(Finding("confirm", "multiple_faces", f"检测到 {len(boxes)} 张脸：请裁剪成只有你一人，或指明哪一位是你"))
    elif boxes[0][2] / size[0] < MIN_FACE_WIDTH_RATIO:
        add(Finding("warn", "face_too_small", "脸在画面中偏小，建议换一张脸更大的照片"))
    try:
        blurry = det.blur(path) < BLUR_THRESHOLD
    except Exception:
        add(Finding("info", "detector_failed", "清晰度检测失败，改为人工确认"))
        return report
    if blurry:
        add(Finding("warn", "blurry", "照片偏模糊，建议换一张更清晰的"))
    return report
