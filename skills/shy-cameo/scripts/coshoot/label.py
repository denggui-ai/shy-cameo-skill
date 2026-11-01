"""Deliver an image: byte-exact copy into the workspace plus a sidecar record.

The original is never re-encoded so OpenAI's C2PA manifest (PNG caBX) survives.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional, Sequence

from .cards import CardError, require_valid
from .library import sha256_file
from .png import has_c2pa

CONSENT_KEYS = ("subject_confirmed", "adult_confirmed", "self_or_consented")


def check_consent(consent: dict) -> None:
    missing = [k for k in CONSENT_KEYS if consent.get(k) is not True]
    if not consent.get("at"):
        missing.append("at")
    if missing:
        raise CardError("blocked_consent", "授权确认未完成：" + "、".join(missing))


def check_photo_consent(consent: dict, photos: Sequence[Path]) -> None:
    """Consent covers exactly the photo bytes the user confirmed, not whatever sits at that path later."""
    check_consent(consent)
    allowed = {p.get("sha256") for p in consent.get("photos") or [] if isinstance(p, dict)}
    missing = [str(p) for p in photos if sha256_file(Path(p)) not in allowed]
    if missing:
        raise CardError("blocked_consent", "这些照片还没有经过授权确认：" + "、".join(missing))


def make_badge(src: Path, dst: Path) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise CardError("badge_unavailable", "未安装 Pillow，无法生成角标派生件（角标为可选功能）")
    with Image.open(src) as im:
        img = im.convert("RGB")
    draw = ImageDraw.Draw(img)
    text = "AI-GENERATED"
    width, height = img.size
    box_w, box_h = max(8 * len(text), width // 6), max(16, height // 40)
    draw.rectangle([width - box_w - 8, height - box_h - 8, width - 8, height - 8], fill=(0, 0, 0))
    draw.text((width - box_w - 4, height - box_h - 6), text, fill=(255, 255, 255))
    img.save(dst, format="PNG")
    return Path(dst)


def deliver(original: Path, run_dir: Path, request: dict, consent: dict, audit: dict,
            frame: Optional[dict] = None, cli_version: Optional[str] = None,
            badge: bool = False) -> dict:
    check_consent(consent)
    original, run_dir = Path(original), Path(run_dir)
    if (run_dir / "sidecar.json").exists():
        raise CardError("already_delivered", "这次生成已经交付过；再拍一张请重新编译")
    run_dir.mkdir(parents=True, exist_ok=True)
    dest = run_dir / ("image" + original.suffix.lower())
    shutil.copyfile(original, dest)
    original_sha = sha256_file(original)
    if sha256_file(dest) != original_sha:
        raise CardError("copy_mismatch", "原图复制后哈希不一致")
    sidecar = {
        "schema_version": "1",
        "run_id": request["run_id"],
        "request_sha256": request["sha256"],
        "original_sha256": original_sha,
        "c2pa_present": has_c2pa(dest),
        "consent": {k: consent[k] for k in CONSENT_KEYS + ("at",)},
        "audit": audit,
        "verdict": "pending",
        "frame_check": frame,
        "codex_cli_version": cli_version,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "badge_path": None,
    }
    if badge:
        sidecar["badge_path"] = str(make_badge(dest, run_dir / "image-badge.png"))
    require_valid(sidecar, "sidecar")
    (run_dir / "sidecar.json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar
