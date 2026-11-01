"""schema_version migrations. Register (kind, from_version) -> step function."""
from __future__ import annotations

import copy
from typing import Callable, Dict, Tuple

from .cards import CardError

CURRENT: Dict[str, str] = {"scene": "2", "character": "1", "request": "1", "sidecar": "1"}
MAX_STEPS = 20
MIGRATIONS: Dict[Tuple[str, str], Callable[[dict], dict]] = {}


def _scene_1_to_2(doc: dict) -> dict:
    # v4 semantics changed (shy characters, play modes), so the user must confirm again.
    doc.pop("style_preset", None)
    doc.update(schema_version="2", style="realistic", aspect="2:3", play_mode="classic_presence")
    for member in doc.get("characters") or []:
        member.setdefault("character_presence", "cropped")
    doc["status"] = "unverified"
    revisions = doc.setdefault("revisions", [])
    last = revisions[-1].get("n", len(revisions)) if revisions else 0
    revisions.append({"n": last + 1, "fields_changed": ["schema_version", "play_mode", "style",
                                                         "aspect", "character_presence"],
                      "status": "unverified"})
    return doc


MIGRATIONS[("scene", "1")] = _scene_1_to_2


def migrate(doc: dict, kind: str) -> dict:
    version = doc.get("schema_version")
    if version is None:
        raise CardError("missing_schema_version", "文档缺少 schema_version")
    target = CURRENT.get(kind, "1")
    for _ in range(MAX_STEPS):
        if version == target:
            return doc
        step = MIGRATIONS.get((kind, version))
        if step is None:
            raise CardError("unsupported_schema_version", f"不支持的 {kind} schema_version：{version}")
        doc = step(copy.deepcopy(doc))
        version = doc.get("schema_version")
    raise CardError("unsupported_schema_version", f"{kind} 迁移步数超过 {MAX_STEPS}")
