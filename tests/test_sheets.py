import json
from pathlib import Path

import pytest

from coshoot import compiler
from coshoot.cards import CardError, schema_errors
from coshoot.library import sha256_bytes
from coshoot.names import NameEntry

FIX = Path(__file__).parent / "fixtures" / "cards"
NAMES = [NameEntry("六小龄童")]


def temp_card(ws):
    """Wukong as a temp draft: qujing has local sheets, mhw has none yet."""
    card = json.loads((FIX / "wukong.json").read_text(encoding="utf-8"))
    card["status"] = "temp_draft"
    for variant in card["variants"]:
        variant["lookalike_check"] = {"status": "pending"}
        del variant["sheets"]
    qujing = card["variants"][1]
    qujing["sheets"] = {}
    for kind in ("head", "body"):
        rel = f"characters/xiyou-wukong/qujing-{kind}.png"
        data = f"qujing-{kind}".encode()
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(data)
        qujing["sheets"][kind] = {"url": rel, "sha256": sha256_bytes(data), "bytes": len(data)}
    return card


def resolver_for(ws):
    return lambda asset: ws / asset["url"]


def test_head_sheet_is_text_only_by_default(tmp_path):
    req = compiler.compile_sheet_request(temp_card(tmp_path), "mhw", "head", resolver_for(tmp_path), NAMES)
    assert req["kind"] == "sheet" and req["referenced_image_paths"] == []
    assert req["card_ref"] == {"character_id": "xiyou/wukong", "variant_id": "mhw", "sheet": "head"}
    assert req["prompt"].startswith(compiler.SHEET_TEXT["head"])
    assert "孙悟空（美猴王时期）" in req["prompt"] and "额头光洁无任何头箍" in req["prompt"]
    assert "衣装" not in req["prompt"] and compiler.SHEET_CLOSING in req["prompt"]
    assert schema_errors(req, "sheet_request") == []


def test_head_sheet_can_reference_another_variant(tmp_path):
    req = compiler.compile_sheet_request(temp_card(tmp_path), "mhw", "head", resolver_for(tmp_path),
                                         NAMES, ref_variant="qujing")
    assert req["referenced_image_paths"] == [str(tmp_path / "characters/xiyou-wukong/qujing-head.png")]
    assert compiler.SHEET_REF_TEXT["head"] in req["prompt"]


def test_body_sheet_references_own_head(tmp_path):
    req = compiler.compile_sheet_request(temp_card(tmp_path), "qujing", "body", resolver_for(tmp_path), NAMES)
    assert req["referenced_image_paths"] == [str(tmp_path / "characters/xiyou-wukong/qujing-head.png")]
    assert compiler.SHEET_REF_TEXT["body"] in req["prompt"]
    assert "衣装：红底金边锁子黄金甲" in req["prompt"] and "随身道具" not in req["prompt"]


def test_body_sheet_requires_own_head_first(tmp_path):
    with pytest.raises(CardError) as exc:
        compiler.compile_sheet_request(temp_card(tmp_path), "mhw", "body", resolver_for(tmp_path), NAMES)
    assert exc.value.code == "head_sheet_first"


@pytest.mark.parametrize("variant,kind,ref,code", [
    ("qujing", "body", "mhw", "bad_sheet_ref"),
    ("mhw", "head", "mhw", "bad_sheet_ref"),
    ("qujing", "head", "mhw", "missing_sheets"),
    ("mhw", "face", None, "unknown_sheet_kind"),
    ("nope", "head", None, "unknown_variant"),
])
def test_sheet_request_errors(tmp_path, variant, kind, ref, code):
    with pytest.raises(CardError) as exc:
        compiler.compile_sheet_request(temp_card(tmp_path), variant, kind, resolver_for(tmp_path),
                                       NAMES, ref_variant=ref)
    assert exc.value.code == code


def test_gold_card_does_not_regenerate_sheets(tmp_path):
    card = temp_card(tmp_path)
    card["status"] = "gold"
    with pytest.raises(CardError) as exc:
        compiler.compile_sheet_request(card, "mhw", "head", resolver_for(tmp_path), NAMES)
    assert exc.value.code == "sheet_not_temp"


def test_actor_name_in_card_text_blocks_sheet(tmp_path):
    card = temp_card(tmp_path)
    card["variants"][0]["identity_features"] += "，像六小龄童"
    with pytest.raises(CardError) as exc:
        compiler.compile_sheet_request(card, "mhw", "head", resolver_for(tmp_path), NAMES)
    assert exc.value.code == "blocked_name"


def test_card_with_only_head_sheet_is_schema_valid(tmp_path):
    card = temp_card(tmp_path)
    del card["variants"][1]["sheets"]["body"]
    assert schema_errors(card, "character") == []


def test_coshoot_compile_sheets_are_optional(tmp_path):
    # Spec v4: sheets are optional references; a variant with only a head sheet still compiles.
    card = temp_card(tmp_path)
    card["status"] = "temp_confirmed"
    del card["variants"][1]["sheets"]["body"]
    scene = json.loads((FIX / "scene-shuiliandong.json").read_text(encoding="utf-8"))
    scene["characters"][0]["variant_id"] = "qujing"
    req = compiler.compile_request(scene, {"xiyou/wukong": card}, [tmp_path / "me.png"],
                                   resolver_for(tmp_path), NAMES)
    assert len(req["referenced_image_paths"]) == 2
