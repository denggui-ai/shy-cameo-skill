"""Gold sheet assets: download Release URLs into a sha256-addressed cache."""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

from .cards import CardError


def is_remote(url: str) -> bool:
    return url.startswith("https://") or url.startswith("http://")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_path(asset: dict, cache_dir: Path) -> Path:
    suffix = Path(urlparse(asset["url"]).path).suffix.lower() or ".png"
    return Path(cache_dir) / asset["sha256"][:2] / (asset["sha256"] + suffix)


def fetch_asset(asset: dict, cache_dir: Path, opener: Optional[Callable] = None) -> Path:
    target = cache_path(asset, cache_dir)
    if target.is_file() and sha256_file(target) == asset["sha256"]:
        return target
    opener = opener or urllib.request.urlopen
    with opener(asset["url"], timeout=60) as resp:
        data = resp.read(asset["bytes"] + 1)  # never buffer more than one byte past the expected size
    if len(data) != asset["bytes"] or sha256_bytes(data) != asset["sha256"]:
        raise CardError("asset_integrity", f"下载的定妆表校验失败：{asset['url']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target


def resolve_sheet(asset: dict, cache_dir: Path, workspace: Path) -> Path:
    if is_remote(asset["url"]):
        path = cache_path(asset, cache_dir)
        if not path.is_file():
            raise CardError("asset_not_fetched", f"定妆表尚未下载，请先运行 fetch：{asset['url']}")
    else:
        root = Path(workspace).resolve()
        path = (root / asset["url"]).resolve()
        if path != root and root not in path.parents:
            raise CardError("asset_outside_workspace", f"定妆表路径越出工作区：{asset['url']}")
        if not path.is_file():
            raise CardError("asset_missing", f"找不到定妆表：{asset['url']}")
    if sha256_file(path) != asset["sha256"]:
        raise CardError("asset_integrity", f"定妆表校验失败：{asset['url']}")
    return path


def fetch_card_assets(card: dict, cache_dir: Path, opener: Optional[Callable] = None) -> List[Path]:
    paths: List[Path] = []
    for variant in card["variants"]:
        for asset in variant.get("sheets", {}).values():
            if is_remote(asset["url"]):
                paths.append(fetch_asset(asset, cache_dir, opener))
    return paths


def promote_card(card: dict, release_base: str, workspace: Path, stage: Path) -> Tuple[dict, List[dict]]:
    """Turn a confirmed temp card into a gold card whose sheets point at Release assets.

    Everything is validated before anything is staged; staged files are byte-exact copies.
    """
    if card["status"] != "temp_confirmed":
        raise CardError("character_not_confirmed", f"角色卡尚未确认：{card['name']}")
    if not release_base.startswith("https://"):
        raise CardError("bad_release_base", f"Release 地址必须是 https：{release_base}")
    workspace, stage = Path(workspace), Path(stage)
    variant_ids = [v["variant_id"] for v in card["variants"]]
    if len(variant_ids) != len(set(variant_ids)):
        raise CardError("duplicate_variant", f"variant_id 重复：{card['name']}")
    gold = copy.deepcopy(card)
    # Sheets are optional (v4); only the kinds a variant actually carries are resolved and staged.
    sources = {(v["variant_id"], kind): resolve_sheet(v["sheets"][kind], workspace / "cache" / "library", workspace)
               for v in gold["variants"] for kind in ("head", "body") if kind in (v.get("sheets") or {})}
    stage.mkdir(parents=True, exist_ok=True)
    uploads: List[dict] = []
    for variant in gold["variants"]:
        for kind in ("head", "body"):
            if (variant["variant_id"], kind) not in sources:
                continue
            src = sources[(variant["variant_id"], kind)]
            name = f"{card['ip']}-{card['id']}-{variant['variant_id']}-{kind}{src.suffix.lower()}"
            dest = stage / name
            shutil.copyfile(src, dest)
            sha = variant["sheets"][kind]["sha256"]
            if sha256_file(dest) != sha:
                raise CardError("copy_mismatch", f"暂存副本哈希不一致：{name}")
            variant["sheets"][kind] = {"url": release_base.rstrip("/") + "/" + name, "sha256": sha,
                                       "bytes": dest.stat().st_size}
            uploads.append({"file": str(dest), "name": name})
    gold["status"] = "gold"
    return gold, uploads
