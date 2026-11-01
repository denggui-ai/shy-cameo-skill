import json
import shutil
from pathlib import Path

import pytest

from coshoot.cards import CardError
from coshoot.migrate import MIGRATIONS, migrate
from coshoot.names import NameEntry, load_names
from coshoot.rules import DEFAULT_LIBRARY, library_errors

FIX = Path(__file__).parent / "fixtures" / "cards"
NAMES = [NameEntry("六小龄童")]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def make_lib(tmp_path):
    lib = tmp_path / "library"
    (lib / "policy").mkdir(parents=True)
    shutil.copy(DEFAULT_LIBRARY / "policy" / "xiyou.json", lib / "policy" / "xiyou.json")
    char_dir = lib / "characters" / "xiyou" / "wukong"
    char_dir.mkdir(parents=True)
    shutil.copy(FIX / "wukong.json", char_dir / "card.json")
    scene = read(FIX / "scene-shuiliandong.json")
    scene["status"] = "gold"
    (lib / "scenes" / "xiyou").mkdir(parents=True)
    write(lib / "scenes" / "xiyou" / "shuiliandong.json", scene)
    return lib


def test_shipped_library_is_clean():
    assert library_errors(DEFAULT_LIBRARY, load_names()) == []


def test_gold_fixture_library_passes(tmp_path):
    assert library_errors(make_lib(tmp_path), NAMES) == []


def test_optional_lookalike_check_does_not_block_library(tmp_path):
    lib = make_lib(tmp_path)
    card_path = lib / "characters" / "xiyou" / "wukong" / "card.json"
    card = read(card_path)
    card["variants"][0]["lookalike_check"]["status"] = "pending"
    write(card_path, card)
    assert not library_errors(lib, NAMES)


def test_non_ascii_path_fails(tmp_path):
    lib = make_lib(tmp_path)
    (lib / "scenes" / "西游").mkdir()
    assert any("路径必须是 ASCII" in e for e in library_errors(lib, NAMES))


def test_scene_referencing_missing_character_fails(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "scenes" / "xiyou" / "shuiliandong.json"
    scene = read(path)
    scene["characters"][0]["character_id"] = "xiyou/bajie"
    write(path, scene)
    assert any("不存在的金牌角色 xiyou/bajie" in e for e in library_errors(lib, NAMES))


def test_actor_name_in_scene_text_fails(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "scenes" / "xiyou" / "shuiliandong.json"
    scene = read(path)
    scene["setting"] = "六小龄童站在洞口"
    write(path, scene)
    assert any("含真实演员姓名 六小龄童" in e for e in library_errors(lib, NAMES))


def test_missing_policy_fails(tmp_path):
    lib = make_lib(tmp_path)
    (lib / "policy" / "xiyou.json").unlink()
    assert any("缺少 policy/xiyou.json" in e for e in library_errors(lib, NAMES))


def test_migrate_current_version_passthrough():
    doc = {"schema_version": "2", "x": 1}
    assert migrate(doc, "scene") == doc


def test_migrate_missing_version():
    with pytest.raises(CardError) as exc:
        migrate({"x": 1}, "scene")
    assert exc.value.code == "missing_schema_version"


def test_migrate_unknown_version():
    with pytest.raises(CardError) as exc:
        migrate({"schema_version": "9"}, "scene")
    assert exc.value.code == "unsupported_schema_version"


def test_registered_migration_applies(monkeypatch):
    monkeypatch.setitem(MIGRATIONS, ("scene", "0"), lambda d: dict(d, schema_version="2", added=True))
    assert migrate({"schema_version": "0"}, "scene") == {"schema_version": "2", "added": True}


def test_actor_name_in_source_ref_fails(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "scenes" / "xiyou" / "shuiliandong.json"
    scene = read(path)
    scene["source_ref"] = "六小龄童版"
    write(path, scene)
    assert any("含真实演员姓名 六小龄童" in e for e in library_errors(lib, NAMES))


def test_actor_name_in_version_labels_fails(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "characters" / "xiyou" / "wukong" / "card.json"
    card = read(path)
    card["version_labels"] = ["版本标签A", "六小龄童版"]
    write(path, card)
    assert any("含真实演员姓名 六小龄童" in e for e in library_errors(lib, NAMES))


def test_actor_name_in_reviewer_fails(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "characters" / "xiyou" / "wukong" / "card.json"
    card = read(path)
    card["variants"][0]["lookalike_check"]["reviewer"] = "六小龄童"
    write(path, card)
    assert any("含真实演员姓名 六小龄童" in e for e in library_errors(lib, NAMES))


def _wukong(lib):
    return lib / "characters" / "xiyou" / "wukong" / "card.json"


def test_rules_reject_duplicate_variant_ids(tmp_path):
    lib = make_lib(tmp_path)
    card = read(_wukong(lib))
    card["variants"][1]["variant_id"] = "mhw"
    write(_wukong(lib), card)
    assert any("variant_id 重复" in e for e in library_errors(lib, NAMES))


def test_rules_rights_tier_must_match_policy(tmp_path):
    lib = make_lib(tmp_path)
    card = read(_wukong(lib))
    card["rights_tier"] = "screen_original"
    write(_wukong(lib), card)
    assert any("rights_tier 与 policy/xiyou.json 不一致" in e for e in library_errors(lib, NAMES))


def test_rules_gold_sheets_must_be_https(tmp_path):
    lib = make_lib(tmp_path)
    card = read(_wukong(lib))
    card["variants"][0]["sheets"]["body"]["url"] = "http://x/y.png"
    write(_wukong(lib), card)
    assert any("https Release 资产" in e for e in library_errors(lib, NAMES))


def test_scene_v1_migrates_to_v2_and_needs_reconfirm():
    v1 = {"schema_version": "1", "id": "s", "ip": "xiyou", "title": "t", "status": "user_confirmed",
          "setting": "x", "characters": [{"character_id": "xiyou/wukong", "variant_id": "mhw",
                                          "position": "right", "action": "递桃"}],
          "user": {"mode": "traveler", "position": "left", "action": "接桃"},
          "framing": "knee_up", "style_preset": "cinematic_still",
          "revisions": [{"n": 1, "fields_changed": [], "status": "user_confirmed"}]}
    v2 = migrate(v1, "scene")
    assert v2["schema_version"] == "2" and "style_preset" not in v2
    assert (v2["style"], v2["aspect"], v2["play_mode"]) == ("realistic", "2:3", "classic_presence")
    assert v2["characters"][0]["character_presence"] == "cropped"
    assert v2["status"] == "unverified"
    assert v2["revisions"][-1] == {"n": 2, "fields_changed": ["schema_version", "play_mode", "style",
                                                              "aspect", "character_presence"],
                                   "status": "unverified"}


def test_scene_v1_migrate_without_revisions_starts_at_one():
    v1 = {"schema_version": "1", "id": "s", "characters": []}
    assert migrate(v1, "scene")["revisions"][-1]["n"] == 1


def test_other_kinds_stay_on_v1():
    doc = {"schema_version": "1", "x": 1}
    assert migrate(doc, "character") == doc and migrate(doc, "request") == doc


def test_gold_sheets_optional_but_https_when_present(tmp_path):
    lib = make_lib(tmp_path)
    card_path = next((lib / "characters").glob("*/*/card.json"))
    card = json.loads(card_path.read_text(encoding="utf-8"))
    for variant in card["variants"]:
        variant.pop("sheets", None)
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    assert not [e for e in library_errors(lib, NAMES) if "定妆表" in e]
    card["variants"][0]["sheets"] = {"body": {"url": "http://x/y.png", "sha256": "0" * 64, "bytes": 1}}
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    assert any("https" in e for e in library_errors(lib, NAMES))


def test_library_scene_cover_without_level_fails(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "scenes" / "xiyou" / "shuiliandong.json"
    scene = read(path)
    scene["characters"][0]["character_presence"] = "cover"
    write(path, scene)
    assert any("cover_level" in e for e in library_errors(lib, NAMES))


def test_library_scene_retired_presence_gets_the_hint(tmp_path):
    lib = make_lib(tmp_path)
    path = lib / "scenes" / "xiyou" / "shuiliandong.json"
    scene = read(path)
    scene["characters"][0]["character_presence"] = "side_profile"
    write(path, scene)
    assert any("已停用" in e for e in library_errors(lib, NAMES))
