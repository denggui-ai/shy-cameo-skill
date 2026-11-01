"""Gold library rules, run locally and in CI for community pull requests."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from .cards import SKILL_ROOT, CardError, load_json, schema_errors
from .compiler import check_cover_level, check_retired_presence
from .names import NameEntry, scan

DEFAULT_LIBRARY = SKILL_ROOT / "library"
RIGHTS_TIERS = ("public_domain", "screen_original", "restricted")


def _character_texts(card: dict) -> List[str]:
    texts = [card["name"], *card.get("version_labels", [])]
    for variant in card.get("variants", []):
        texts += [variant.get(k, "") for k in ("label", "identity_features", "costume", "props", "exclusions")]
        texts.append(variant.get("lookalike_check", {}).get("reviewer", ""))
    return texts


def _scene_texts(card: dict) -> List[str]:
    user = card.get("user", {})
    texts = [card.get("title", ""), card.get("setting", ""), card.get("props", ""),
             card.get("source_ref", ""),
             user.get("action", ""), user.get("role", ""), user.get("outfit", "")]
    for member in card.get("characters", []):
        texts += [member.get("action", ""), member.get("expression", "")]
    return texts


def _name_errors(rel: str, texts: List[str], names: Sequence[NameEntry]) -> List[str]:
    hits = sorted({h.matched for t in texts if t for h in scan(t, names)})
    return [f"{rel}: 含真实演员姓名 {'、'.join(hits)}"] if hits else []


def _policy_errors(lib_root: Path, errors: List[str]) -> Dict[str, dict]:
    policies: Dict[str, dict] = {}
    for path in sorted((lib_root / "policy").glob("*.json")):
        if path.name == "actor-names.json":
            continue
        doc = load_json(path)
        if doc.get("schema_version") != "1" or doc.get("ip") != path.stem or doc.get("rights_tier") not in RIGHTS_TIERS:
            errors.append(f"policy/{path.name}: 需要 schema_version=1、ip 与文件名一致、合法 rights_tier")
        policies[path.stem] = doc
    return policies


def _character_errors(lib_root: Path, policies: Dict[str, dict], names: Sequence[NameEntry],
                      errors: List[str]) -> Dict[str, dict]:
    chars: Dict[str, dict] = {}
    for path in sorted((lib_root / "characters").glob("*/*/card.json")):
        rel = path.relative_to(lib_root).as_posix()
        ip, cid = path.parts[-3], path.parts[-2]
        card = load_json(path)
        problems = schema_errors(card, "character")
        if problems:
            errors.extend(f"{rel}: {p}" for p in problems)
            continue
        if (card["ip"], card["id"]) != (ip, cid):
            errors.append(f"{rel}: ip/id 与目录不一致")
        if ip not in policies:
            errors.append(f"{rel}: 缺少 policy/{ip}.json")
        elif card["rights_tier"] != policies[ip].get("rights_tier"):
            errors.append(f"{rel}: rights_tier 与 policy/{ip}.json 不一致")
        if card["status"] != "gold":
            errors.append(f"{rel}: 金牌库只收 status=gold")
        variant_ids = [v["variant_id"] for v in card["variants"]]
        if len(variant_ids) != len(set(variant_ids)):
            errors.append(f"{rel}: variant_id 重复")
        for variant in card["variants"]:
            # v4: characters never show their face, so sheets are optional; shipped ones must be Release assets.
            sheets = variant.get("sheets") or {}
            if not all(a["url"].startswith("https://") for a in sheets.values()):
                errors.append(f"{rel}: variant {variant['variant_id']} 定妆表必须是 https Release 资产")
        errors.extend(_name_errors(rel, _character_texts(card), names))
        chars[f"{ip}/{cid}"] = card
    return chars


def _scene_errors(lib_root: Path, chars: Dict[str, dict], names: Sequence[NameEntry],
                  errors: List[str]) -> None:
    for path in sorted((lib_root / "scenes").glob("*/*.json")):
        rel = path.relative_to(lib_root).as_posix()
        card = load_json(path)
        try:
            check_retired_presence(card)
        except CardError as exc:
            errors.append(f"{rel}: {exc.message}")
            continue
        problems = schema_errors(card, "scene")
        if problems:
            errors.extend(f"{rel}: {p}" for p in problems)
            continue
        try:
            check_cover_level(card)
        except CardError as exc:
            errors.append(f"{rel}: {exc.message}")
        if (card["ip"], card["id"]) != (path.parts[-2], path.stem):
            errors.append(f"{rel}: ip/id 与路径不一致")
        if card["status"] != "gold":
            errors.append(f"{rel}: 金牌库只收 status=gold")
        for member in card["characters"]:
            char = chars.get(member["character_id"])
            if char is None:
                errors.append(f"{rel}: 引用了不存在的金牌角色 {member['character_id']}")
            elif member["variant_id"] not in {v["variant_id"] for v in char["variants"]}:
                errors.append(f"{rel}: 角色 {member['character_id']} 没有 variant {member['variant_id']}")
        errors.extend(_name_errors(rel, _scene_texts(card), names))


def library_errors(lib_root: Path, names: Sequence[NameEntry]) -> List[str]:
    lib_root = Path(lib_root)
    errors: List[str] = []
    for path in sorted(lib_root.rglob("*")):
        rel = path.relative_to(lib_root).as_posix()
        if not rel.isascii():
            errors.append(f"{rel}: 路径必须是 ASCII")
    policies = _policy_errors(lib_root, errors)
    chars = _character_errors(lib_root, policies, names, errors)
    _scene_errors(lib_root, chars, names, errors)
    return errors
