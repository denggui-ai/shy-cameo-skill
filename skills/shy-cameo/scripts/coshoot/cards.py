"""Card / document loading and schema validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .schema_lite import validate

SKILL_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = SKILL_ROOT / "schema"
KINDS: Dict[str, str] = {
    "character": "character-card",
    "scene": "scene-card",
    "request": "request",
    "sheet_request": "sheet-request",
    "sidecar": "sidecar",
    "set": "set-card",
    "project": "project",
}


class CardError(Exception):
    """A user-facing, coded failure; `code` is a status word or error slug."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_schema(kind: str) -> Dict[str, Any]:
    return load_json(SCHEMA_DIR / f"{KINDS[kind]}.schema.json")


def schema_errors(obj: Any, kind: str) -> List[str]:
    return validate(obj, load_schema(kind))


def require_valid(obj: Any, kind: str) -> None:
    errors = schema_errors(obj, kind)
    if errors:
        raise CardError(f"invalid_{kind}", "; ".join(errors))


def find_variant(card: dict, variant_id: str) -> dict:
    for variant in card["variants"]:
        if variant["variant_id"] == variant_id:
            return variant
    raise CardError("unknown_variant", f"角色 {card['name']} 没有时期版本 {variant_id}")
