"""Output framing check: only the user's face shows (shy characters never do), not drifted to full body."""
from __future__ import annotations

from pathlib import Path
import struct
import zlib
from typing import List, Union

from .detect import Detector, default_detector
from .findings import Finding, worst
from .png import image_size, png_decode_error
from .library import sha256_file

MIN_FACE_HEIGHT_RATIO = 0.08
# Detections far smaller than the main face are mostly texture (tiger skin, armour, bulbs; runs 45-53).
EXTRA_FACE_MIN_RATIO = 0.5


def check_frame(path: Path, framing: str, detector: Union[str, Detector, None] = "auto") -> dict:
    path = Path(path)
    try:
        if png_decode_error(path):
            raise ValueError("invalid PNG pixels")
        size = image_size(path)
        data = path.read_bytes()
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            pos, kinds = 8, []
            while pos < len(data):
                length, kind = struct.unpack('>I4s', data[pos:pos+8])
                end = pos + 12 + length
                if end > len(data) or zlib.crc32(data[pos+4:end-4]) & 0xffffffff != struct.unpack('>I', data[end-4:end])[0]:
                    raise ValueError('invalid PNG chunk')
                kinds.append(kind)
                pos = end
            if not kinds or kinds[0] != b'IHDR' or b'IDAT' not in kinds or kinds[-1] != b'IEND':
                raise ValueError('incomplete PNG')
        elif not data.endswith(b'\xff\xd9'):
            size = None
    except (OSError, ValueError, struct.error):
        size = None
    if not size or min(size) <= 0:
        return {'framing': framing, 'faces': None, 'level': 'block',
                'findings': [Finding('block', 'bad_image', '图片不存在、不可读或格式无效').to_dict()]}
    det = default_detector() if detector == "auto" else detector
    findings: List[Finding] = []
    boxes = None
    faces = None
    if det is None:
        findings.append(Finding("info", "detector_unavailable", "未安装可用的 opencv 4.x，构图检查改为人工确认"))
    else:
        try:
            boxes = det.faces(path)
        except Exception:
            boxes = None
            findings.append(Finding("info", "detector_failed", "人脸检测失败（图片可能已损坏），构图检查改为人工确认"))
    if boxes is not None:
        faces = len(boxes)
        size = image_size(path)
        if not boxes:
            findings.append(Finding("warn", "faces_not_found", "没有检测到脸，请人工确认主角的脸清楚可见"))
        else:
            main = max(b[3] for b in boxes)
            extra = sum(1 for b in boxes if b[3] >= main * EXTRA_FACE_MIN_RATIO) - 1
            if extra > 0:
                findings.append(Finding("warn", "extra_faces",
                                        f"除主角外还检测到 {extra} 张接近主角大小的脸；角色应当不露脸，请确认没有多出人脸或镜中正脸"))
        if boxes and size and max(b[3] for b in boxes) / size[1] < MIN_FACE_HEIGHT_RATIO and framing not in ("full_body", "wide"):
            findings.append(Finding("warn", "framing_drift",
                                    f"人物在画面中偏小，可能被拉成了全身，与景别 {framing} 不符"))
    return {"framing": framing, "faces": faces, "level": worst(findings), 'image_sha256': sha256_file(path),
            "findings": [f.to_dict() for f in findings]}
