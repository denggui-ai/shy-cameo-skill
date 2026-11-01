from pathlib import Path

import pytest

from coshoot.cards import CardError, find_variant, load_json, require_valid, schema_errors

FIX = Path(__file__).parent / "fixtures" / "cards"


def wukong():
    return load_json(FIX / "wukong.json")


def scene():
    return load_json(FIX / "scene-shuiliandong.json")


def test_fixture_cards_are_valid():
    assert schema_errors(wukong(), "character") == []
    assert schema_errors(scene(), "scene") == []


def test_scene_rejects_raw_user_utterance_field():
    s = scene()
    s["user_utterance"] = "我想和六小龄童合影"
    assert "$: unexpected property 'user_utterance'" in schema_errors(s, "scene")


def test_scene_rejects_three_characters_but_accepts_full_body():
    s = scene()
    s["characters"] = s["characters"] * 3
    s["framing"] = "full_body"
    errors = schema_errors(s, "scene")
    assert "$.characters: more than 2 items" in errors
    assert not any(e.startswith("$.framing:") for e in errors)


def test_non_ascii_slug_rejected():
    c = wukong()
    c["id"] = "悟空"
    assert any(e.startswith("$.id: does not match") for e in schema_errors(c, "character"))


def test_require_valid_raises_card_error_with_code():
    c = wukong()
    del c["variants"]
    with pytest.raises(CardError) as exc:
        require_valid(c, "character")
    assert exc.value.code == "invalid_character"


def test_find_variant():
    assert find_variant(wukong(), "mhw")["label"] == "美猴王时期"
    with pytest.raises(CardError) as exc:
        find_variant(wukong(), "nope")
    assert exc.value.code == "unknown_variant"


def test_request_and_sidecar_schemas_accept_minimal_valid_docs():
    req = {"schema_version": "1", "run_id": "20261010-120000-abcdef", "prompt": "p",
           "referenced_image_paths": ["/tmp/a.png"],
           "card_ref": {"scene_id": "xiyou/shuiliandong", "revision": 1},
           "max_refs": 5, "sha256": "0" * 64}
    assert schema_errors(req, "request") == []
    side = {"schema_version": "1", "run_id": req["run_id"], "request_sha256": "0" * 64,
            "original_sha256": "1" * 64, "c2pa_present": True,
            "consent": {"subject_confirmed": True, "adult_confirmed": True,
                        "self_or_consented": True, "at": "2026-10-10T12:00:00"},
            "audit": {"status": "unverified", "reason": "no log"}, "verdict": "pending",
            "frame_check": None, "codex_cli_version": None,
            "created_at": "2026-10-10T12:00:00", "badge_path": None}
    assert schema_errors(side, "sidecar") == []


def test_variant_episodes_optional_and_validated():
    c = wukong()
    assert "episodes" not in c["variants"][0] and schema_errors(c, "character") == []
    c["variants"][0]["episodes"] = ["重返水帘洞（第三回）", "竖旗称齐天大圣（第四回）"]
    assert schema_errors(c, "character") == []
    c["variants"][0]["episodes"] = []
    assert schema_errors(c, "character")
