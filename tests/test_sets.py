import json
from pathlib import Path

import pytest

from coshoot import sets
from coshoot.cards import CardError, load_json

FIX = Path(__file__).parent / "fixtures" / "cards"
POSES = [("close_up", "left", "侧身坐着，转头正脸看向镜头"), ("knee_up", "center", "踮脚伸手去够高处的桃"),
         ("mid_interactive", "right", "弯腰双手接桃，低头看着桃笑"), ("waist_up", "left", "背靠门框回头，看向镜头"),
         ("waist_up", "center", "坐着端详手里的桃，脸朝镜头")]


def vary_poses(shots):
    """Give the five shots different framing, position and gaze so pose_too_similar stays quiet."""
    for index, (shot, (framing, position, action)) in enumerate(zip(shots, POSES)):
        shot["setting"] += f"；分镜空间 {index}: " + ("准备间", "故事大空间", "互动布景", "门边", "准备间出口")[index]
        shot["framing"] = framing
        shot["user"].update(position=position, action=action)
    return shots


def make_card(**shot_overrides):
    scene = load_json(FIX / "scene-shuiliandong.json")
    shots = []
    for role in sets.ROLES:
        shot = json.loads(json.dumps(dict(scene, id=f"hgs-{role}", **shot_overrides)))
        if role == "shy":
            shot["characters"][0].update(character_presence="cover", cover_level="face")
        shots.append(shot)
    return {"schema_version": "1", "set_id": "hgs1", "status": "user_confirmed", "shots": vary_poses(shots)}


def test_validate_requires_five_consistent_confirmed_shots():
    assert sets.ROLES == ("cover", "wide", "interaction", "shy", "ending") and sets.SET_SIZE == 5
    sets.validate_set_card(make_card())
    card = make_card()
    card["shots"] = card["shots"][:3]
    with pytest.raises(CardError) as exc:
        sets.validate_set_card(card)
    assert exc.value.code == "invalid_set"
    card = make_card()
    del card["shots"][3]  # an old four-shot card gets the migration hint
    with pytest.raises(CardError) as exc:
        sets.validate_set_card(card)
    assert exc.value.code == "set_size_changed"
    card = make_card()
    card["shots"][2]["style"] = "anime"
    with pytest.raises(CardError) as exc:
        sets.validate_set_card(card)
    assert exc.value.code == "set_inconsistent"
    card = make_card(status="unverified")
    with pytest.raises(CardError) as exc:
        sets.validate_set_card(card)
    assert exc.value.code == "scene_not_confirmed"


def test_first_shot_failure_cancels_rest(tmp_path):
    ledger = sets.load_ledger(tmp_path, make_card())
    with pytest.raises(CardError) as exc:
        sets.require_claimable(ledger, 2)
    assert exc.value.code == "chain_not_ready"
    sets.claim(ledger, 1, "r1")
    sets.record(tmp_path, ledger, 1, "rejected")
    assert [i["status"] for i in ledger["items"]] == ["rejected"] + ["cancelled"] * 4
    with pytest.raises(CardError) as exc:
        sets.require_claimable(ledger, 2)
    assert exc.value.code == "set_cancelled"


def test_first_shot_success_registers_chain(tmp_path, png_factory):
    img = tmp_path / "gen.png"
    img.write_bytes(png_factory())
    ledger = sets.load_ledger(tmp_path, make_card())
    sets.claim(ledger, 1, "r1")
    with pytest.raises(CardError) as exc:
        sets.record(tmp_path, ledger, 1, "generated")
    assert exc.value.code == "missing_image"
    sets.record(tmp_path, ledger, 1, "generated", str(img))
    chain = Path(ledger["chain_image"])
    assert chain == (tmp_path / "outputs" / "sets" / "hgs1" / "chain.png").resolve()
    assert chain.read_bytes() == img.read_bytes()
    sets.require_claimable(ledger, 2)
    sets.claim(ledger, 2, "r2")
    with pytest.raises(CardError) as exc:
        sets.claim(ledger, 2, "r2b")
    assert exc.value.code == "shot_already_claimed"
    sets.save_ledger(tmp_path, make_card(), ledger)
    assert sets.load_ledger(tmp_path, make_card()) == ledger


def _set_with(presences):
    import json
    from pathlib import Path
    scene = json.loads((Path(__file__).parent / "fixtures" / "cards" / "scene-shuiliandong.json").read_text(encoding="utf-8"))
    shots = []
    for role, presence in zip(sets.ROLES, presences):
        shot = json.loads(json.dumps(scene))
        shot["id"] = f"s-{role}"
        shot["characters"][0]["character_presence"] = presence
        if presence == "cover":
            shot["characters"][0]["cover_level"] = "face"
        shots.append(shot)
    return {"schema_version": "1", "set_id": "s", "status": "user_confirmed", "shots": vary_poses(shots)}


def test_cover_can_be_selected_on_any_shot():
    sets.validate_set_card(_set_with(["hand", "cover", "hand", "cover", "back"]))


def test_shy_character_need_not_hold_prop_on_fourth_shot():
    sets.validate_set_card(_set_with(["hand", "shadow", "hand", "peek", "back"]))


def test_solo_and_genre_shy_shot_needs_no_cover():
    for mode in ("location_checkin", "opera_costume", "genre_scene"):
        card = _set_with(["hand"] * 5)
        for shot in card["shots"]:
            shot["play_mode"] = mode
            shot["characters"] = []
        sets.validate_set_card(card)


def test_retired_presence_in_set_card_gets_the_hint():
    with pytest.raises(CardError) as exc:
        sets.validate_set_card(_set_with(["hand", "side_profile", "hand", "cover", "back"]))
    assert exc.value.code == "presence_retired"


def test_set_card_checks_cover_level_on_every_shot():
    card = _set_with(["hand", "shadow", "hand", "cover", "back"])
    del card["shots"][3]["characters"][0]["cover_level"]
    with pytest.raises(CardError) as exc:
        sets.validate_set_card(card)
    assert exc.value.code == "cover_level_required"


def test_shy_shot_may_cover_two_characters():
    card = _set_with(["hand", "shadow", "hand", "cover", "back"])
    shot = card["shots"][3]
    shot["characters"].append(dict(shot["characters"][0]))
    sets.validate_set_card(card)


def test_old_four_item_ledger_is_rejected(tmp_path):
    card = make_card()
    path = sets.set_dir(tmp_path, card["set_id"]) / sets.LEDGER_NAME
    path.parent.mkdir(parents=True)
    old = {"set_id": card["set_id"], "chain_image": None, "chain_sha256": None,
           "items": [{"index": i, "role": r, "run_id": None, "status": "pending"}
                     for i, r in enumerate(("cover", "wide", "interaction", "ending"), 1)]}
    path.write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(CardError) as exc:
        sets.load_ledger(tmp_path, card)
    assert exc.value.code == "ledger_mismatch"


def test_pose_too_similar_needs_three_framings(capsys):
    card = make_card()
    for shot in card["shots"]:
        shot["framing"] = "waist_up"
    card["shots"][0]["framing"] = "close_up"
    sets.validate_set_card(card)
    assert "景别" in capsys.readouterr().err


def test_pose_too_similar_needs_two_positions(capsys):
    card = make_card()
    for shot in card["shots"]:
        shot["user"]["position"] = "center"
    sets.validate_set_card(card)
    assert "站位" in capsys.readouterr().err


def test_pose_too_similar_caps_looking_at_camera(capsys):
    card = make_card()
    for shot in card["shots"][:3]:
        shot["user"]["action"] = "笑着望向镜头"
    sets.validate_set_card(card)
    assert "镜头" in capsys.readouterr().err


def test_too_many_face_away_poses_get_an_identity_advisory(capsys):
    card = make_card()
    card["shots"][4]["user"]["action"] = "坐着低头看手里的桃"
    sets.validate_set_card(card)
    err = capsys.readouterr().err
    assert "第 4 张主角露脸时侧脸、回头或歪头" in err
    assert "第 3、5 张主角露脸时低头或仰头，超过 1 张" in err


def test_face_count_advisory(capsys):
    # D25: one or two clear face shots per set, the cover among them.
    card = make_card()
    sets.validate_set_card(card)
    assert "第 1、2、3、4、5 张都露脸，超过 2 张" in capsys.readouterr().err
    for shot in card["shots"][1:4]:
        shot["user"].update(action="背对镜头走向宫门", presence="back")
    sets.validate_set_card(card)
    err = capsys.readouterr().err
    assert "张都露脸" not in err and "（封面）不露脸" not in err and "都不露脸" not in err
    card["shots"][0]["user"].update(action="背对镜头走向宫门", presence="back")
    sets.validate_set_card(card)
    assert "第 1 张（封面）不露脸" in capsys.readouterr().err
    card["shots"][4]["user"].update(action="背对镜头走向宫门", presence="back")
    sets.validate_set_card(card)
    assert "5 张都不露脸" in capsys.readouterr().err


def test_waist_up_face_cover_gets_a_close_up_advisory(capsys):
    # D34: 2026-10-25 waist-up covers did not look like the user; the close-up retake did.
    card = make_card()
    sets.validate_set_card(card)
    assert "封面）露脸但不是近景" not in capsys.readouterr().err
    card["shots"][0]["framing"] = "waist_up"
    sets.validate_set_card(card)
    assert "第 1 张（封面）露脸但不是近景（close_up）" in capsys.readouterr().err
    card["shots"][0]["user"].update(action="背对镜头走向宫门", presence="back")
    sets.validate_set_card(card)
    assert "封面）露脸但不是近景" not in capsys.readouterr().err


def test_hands_only_companion_set_gets_a_body_shot_advisory(capsys):
    # D26: at least one mid-ground back shot so the companion reads as the character.
    card = make_card()
    sets.validate_set_card(card)
    assert "陪同角色整套只露手" in capsys.readouterr().err
    card["shots"][4]["characters"][0]["character_presence"] = "cropped"  # head out of frame is not a back shot
    sets.validate_set_card(card)
    assert "陪同角色整套只露手" in capsys.readouterr().err
    card["shots"][4]["characters"][0]["character_presence"] = "back"
    sets.validate_set_card(card)
    assert "陪同角色整套只露手" not in capsys.readouterr().err
    for shot in card["shots"]:
        shot["characters"] = []
    sets.validate_set_card(card)
    assert "陪同角色整套只露手" not in capsys.readouterr().err


def test_cover_with_only_a_paw_gets_a_recognisability_advisory(capsys):
    # D29: the cover must name the companion without a hint; a paw alone does not.
    card = make_card()
    card["shots"][4]["characters"][0]["character_presence"] = "back"
    sets.validate_set_card(card)
    assert "封面）陪同角色只露手" in capsys.readouterr().err
    card["shots"][0]["characters"][0]["character_presence"] = "back"
    sets.validate_set_card(card)
    assert "封面）陪同角色只露手" not in capsys.readouterr().err
    card["shots"][0]["characters"] = []
    sets.validate_set_card(card)
    assert "封面）陪同角色只露手" not in capsys.readouterr().err


def test_wide_face_shot_gets_a_likeness_advisory(capsys):
    card = make_card()
    card["shots"][1]["framing"] = "full_body"
    sets.validate_set_card(card)
    assert "第 2 张露脸却用全身或远景" in capsys.readouterr().err
    card["shots"][1]["user"].update(action="背对镜头走向宫门", presence="back")
    sets.validate_set_card(card)
    assert "露脸却用全身或远景" not in capsys.readouterr().err


def test_single_face_away_shot_now_gets_an_advisory(capsys):
    # D20: no profile or look-back on face shots at all (was: more than two).
    card = make_card()
    for shot in card["shots"]:
        shot["user"]["action"] = "脸朝镜头，目光看手里的信"
    card["shots"][2]["user"]["action"] = "侧脸望向窗外"
    sets.validate_set_card(card)
    assert "第 3 张主角露脸时侧脸、回头或歪头" in capsys.readouterr().err


def test_one_tilted_head_shot_per_set_is_allowed(capsys):
    # Owner 2026-10-23: keep one mood shot such as the Wukong "head down holding the crown".
    card = make_card()
    for shot in card["shots"]:
        shot["user"]["action"] = "脸朝镜头，目光看手里的信"
    card["shots"][4]["user"]["action"] = "低头捧着凤冠端详，脸仍朝镜头"
    sets.validate_set_card(card)
    assert "低头或仰头" not in capsys.readouterr().err
    card["shots"][1]["user"]["action"] = "仰头够高处架子上的金箍棒"
    sets.validate_set_card(card)
    assert "第 2、5 张主角露脸时低头或仰头" in capsys.readouterr().err


def test_faceless_shots_do_not_count_as_face_away(capsys):
    card = make_card()
    card["shots"][4]["user"].update(action="背对镜头走向宫门", presence="back")
    sets.validate_set_card(card)
    assert "主角低头" not in capsys.readouterr().err


def test_face_away_pose_skips_negation():
    for text, hit in (("低头看信", True), ("背靠门框回头，看向镜头", True), ("侧脸望向窗外", True), ("歪头笑", True), ("头正不歪头", False),
                      ("不要低头，脸朝镜头", False), ("没有回头", False), ("脸朝镜头，目光看熊猫", False)):
        assert sets.face_away_pose(text) is hit, text


def test_camera_gaze_counts_synonyms_and_skips_negation():
    for text, hit in (("直视镜头", True), ("凝视着镜头", True), ("面向镜头笑", True), ("看向镜头", True),
                      ("不看镜头，看手里的桃", False), ("没有看向镜头", False), ("背对镜头", False)):
        assert bool(sets.camera_gaze(text)) is hit, text


def test_camera_gaze_reverse_audit_cases():
    # Stage-4 reverse audit: negations a few characters before the verb, "背对", gaze past the camera.
    misses = ("低头看道具，不要看向镜头", "不再看向镜头", "背对着镜头", "没有回头看镜头", "并未看向镜头",
              "从未看镜头", "不要看镜头", "看向镜头外的角色", "望向镜头后方的桃林", "别朝镜头看", "从不看镜头", "背朝镜头", "背对镜头站着", "不面对镜头", "不曾看向镜头")
    hits = ("看了一眼镜头", "朝镜头眨眼", "冲镜头笑", "直面镜头", "目视镜头", "冲着镜头比心",
            "不慌不忙，看向镜头", "不时看向镜头", "背靠门框回头，看向镜头", "毫不犹豫看向镜头", "情不自禁看向镜头",
            "不经意间看向镜头", "不禁看向镜头", "不由得看向镜头", "毫不犹豫地看向镜头", "弓背看向镜头",
            "瞥向镜头", "对镜头微笑", "面对镜头", "特别看向镜头", "告别后回头看向镜头")
    for text in misses:
        assert not sets.camera_gaze(text), text
    for text in hits:
        assert sets.camera_gaze(text), text


@pytest.mark.parametrize("action,expected", [
    ("侧身朝右前方收件箱，脸自然朝镜头保留四分之三正面；目光落在叶纹标记。", False),
    ("身体与脸均朝镜头左前方，目光沿手指看向前左方。", False),
    ("身体面向镜头略转左，脸部清晰；眼神看路牌而非镜头。", False),
    ("正面偏左三分之四朝镜头，脸清楚；视线看下一块石头。", False),
    ("肩与脸适度朝镜头打开，脸无遮挡；目光看投信口。", False),
    ("面向镜头，目光落在镜头外的同伴身上。", False),
    ("脸朝镜头，低头看手里的信。", False),
    ("身体朝镜头，目光没有看向镜头。", False),
    ("看向镜头左侧的路牌。", False),
    ("看向镜头上方的时钟。", False),
    ("面向镜头，眼神温柔。", True),
    ("脸朝镜头，目光没有落在信上。", True),
    ("脸朝镜头，目光落在信上，随后看向镜头。", True),
    ("身体面向信箱，目光看向镜头。", True),
    ("目光落在叶纹标记，随后朝镜头眨眼。", True),
    ("脸朝镜头，目光落在镜头上。", True),
    ("侧身，视线投向镜头。", True),
    ("脸朝镜头，视线投向镜头左侧的路牌。", False),
])
def test_camera_gaze_respects_explicit_eye_target(action, expected):
    assert sets.camera_gaze(action) is expected


def test_explicit_gaze_away_does_not_add_a_camera_gaze_advisory(capsys):
    card = make_card()
    for shot, target in zip(card["shots"], ("信封", "路牌", "石头", "投信口", "封蜡")):
        shot["user"]["action"] = f"脸朝镜头清楚可辨，目光落在{target}上。"
    for shot in card["shots"][1:4]:
        shot["user"]["presence"] = "back"  # keep the D25 face-count advisory out of this check
    card["shots"][0]["characters"][0]["character_presence"] = "back"  # and the D26 / D29 ones
    card["shots"][4]["camera_angle"] = "high"  # and the D33 face-pair one
    sets.validate_set_card(card)
    assert capsys.readouterr().err == ""


def test_cover_pose_gesture_gets_a_film_still_advisory(capsys):
    # D31: a V-sign cover reads as a selfie; suggest a story action instead.
    card = make_card()
    card["shots"][0]["user"]["action"] = "坐在化妆椅上对镜头比V字手势，看向镜头笑"
    sets.validate_set_card(card)
    assert "对镜头摆拍手势" in capsys.readouterr().err
    card["shots"][0]["user"]["action"] = "双手在腰间抻平短褂下摆，看向镜头笑"
    sets.validate_set_card(card)
    assert "对镜头摆拍手势" not in capsys.readouterr().err
    card["shots"][0]["user"]["action"] = "双手在腰间抻平戏服下摆，不比V、不比心，看向镜头浅笑"
    sets.validate_set_card(card)
    assert "对镜头摆拍手势" not in capsys.readouterr().err


def _two_face_card(first, fourth):
    """Shots 1 and 4 show the face; the rest are backs, so only the pair under test is compared."""
    card = make_card()
    for n, shot in enumerate(card["shots"], 1):
        if n in (1, 4):
            framing, angle, action = first if n == 1 else fourth
            shot["framing"] = framing
            shot.pop("camera_angle", None)
            if angle:
                shot["camera_angle"] = angle
            shot["user"]["action"] = action
        else:
            shot["user"].update(action="背对镜头走向洞口", presence="back")
    return card


def test_same_set_face_shots_need_two_differences(capsys):
    # D33, Wukong r1 shots 1/4: only the framing changed between the two face shots.
    card = _two_face_card(("close_up", None, "刚走到洞口，双手垂在身侧；看向镜头，带着惊喜"),
                          ("waist_up", None, "站在岩台上，双手垂在身侧；看向镜头，有点不舍"))
    sets.validate_set_card(card)
    err = capsys.readouterr().err
    assert "第 1 和第 4 张露脸" in err and "D33" in err
    # r2: framing, angle and sit/stand all changed.
    card = _two_face_card(("close_up", None, "站在洞口台阶上，双手垂在身侧；看向镜头，带着惊喜"),
                          ("waist_up", "high", "坐在石阶上，双手搭在膝上；看向镜头，闭嘴浅笑"))
    sets.validate_set_card(card)
    assert "D33" not in capsys.readouterr().err


def test_face_shot_big_laugh_advisory(capsys):
    card = _two_face_card(("close_up", None, "站在洞口，看向镜头"),
                          ("waist_up", "high", "坐在石阶上，抬头看向镜头，开怀大笑"))
    sets.validate_set_card(card)
    assert "第 4 张露脸写了大笑/露齿" in capsys.readouterr().err


def test_face_shot_negated_laugh_skipped(capsys):
    card = _two_face_card(("close_up", None, "站在洞口，看向镜头，不露齿大笑"),
                          ("waist_up", "high", "坐在石阶上，看向镜头，闭嘴浅笑；不露齿"))
    sets.validate_set_card(card)
    assert "大笑/露齿" not in capsys.readouterr().err


def test_face_shot_holding_object_advisory(capsys):
    card = _two_face_card(("close_up", None, "站在洞口，看向镜头"),
                          ("waist_up", "high", "坐在石阶上，双手捧着一只椰壳碗，看向镜头"))
    sets.validate_set_card(card)
    assert "第 4 张露脸手里拿着东西" in capsys.readouterr().err


def test_hands_only_shot_holding_is_fine(capsys):
    card = _two_face_card(("close_up", None, "站在洞口，看向镜头"),
                          ("waist_up", "high", "坐在石阶上，看向镜头"))
    card["shots"][2]["user"].update(action="双手捧着一只椰壳碗", presence="hands")
    sets.validate_set_card(card)
    assert "手里拿着东西" not in capsys.readouterr().err


def test_user_gripping_long_weapon_advisory(capsys):
    card = _two_face_card(("close_up", None, "站在洞口，看向镜头"),
                          ("waist_up", "high", "站在岩台上，双手轻轻扶着身旁那根长棒，看向镜头"))
    sets.validate_set_card(card)
    assert "第 4 张主角握着长兵器" in capsys.readouterr().err
    card["shots"][3]["user"]["action"] = "坐在石阶上，看向镜头"
    card["shots"][4]["user"]["action"] = "背对镜头，双手握住金箍棒高高举起"
    sets.validate_set_card(card)
    assert "第 5 张主角握着长兵器" in capsys.readouterr().err


def test_episode_mismatch_advisory(capsys):
    card = make_card()
    variant = dict(variant_id="mhw", episodes=["重返水帘洞（第三回）", "竖旗称齐天大圣（第四回）"])
    characters = {"xiyou/wukong": {"variants": [variant]}}
    card["shots"][0]["film_context"] = "《西游记》：悟空在花果山随便逛逛"
    sets.check_episode_match(card["shots"], characters)
    assert "造型和情节对不上" in capsys.readouterr().err
    card["shots"][0]["film_context"] = "《西游记》原著第三回：悟空重返水帘洞，群猴迎接"
    sets.check_episode_match(card["shots"], characters)
    assert "造型和情节对不上" not in capsys.readouterr().err
    variant.pop("episodes")
    card["shots"][0]["film_context"] = "随便逛逛"
    sets.check_episode_match(card["shots"], characters)
    assert "造型和情节对不上" not in capsys.readouterr().err


def test_plain_negation_does_not_swallow_affirmative_words():
    # codex-review be334f6: 忍不住 / 告别 / 毫不 are not negations of the action that follows.
    assert sets._plain_hit(sets.BIG_LAUGH, "忍不住大笑")
    assert sets._plain_hit(sets.HOLDING, "告别时捧着碗")
    assert sets._plain_hit(sets.LONG_WEAPON_GRIP, "毫不犹豫握住金箍棒")
    assert sets._plain_hit(sets.BIG_LAUGH, "不禁大笑") and sets._plain_hit(sets.BIG_LAUGH, "情不自禁大笑")
    assert not sets._plain_hit(sets.BIG_LAUGH, "不露齿大笑")
    assert not sets._plain_hit(sets.HOLDING, "手不握剑柄")


def test_negated_sitting_counts_as_standing(capsys):
    card = _two_face_card(("close_up", None, "站在门口，看向镜头"),
                          ("waist_up", None, "不坐下，站在石阶旁，看向镜头"))
    sets.validate_set_card(card)
    assert "第 1 和第 4 张露脸" in capsys.readouterr().err


def test_both_face_shots_gazing_at_camera_get_doing_hint(capsys):
    # lessons 29/34/35: two face shots both looking at the camera read as one mould side by side.
    card = _two_face_card(("close_up", None, "站在沙脊脚下，双手垂在身侧；看向镜头，闭嘴浅笑"),
                          ("waist_up", "high", "坐在栈道边，双手撑在身侧；抬眼看向镜头，满足地微笑"))
    sets.validate_set_card(card)
    err = capsys.readouterr().err
    assert "第 1、4 张露脸都看镜头" in err and "在做事" in err
    # Abao r5-3 held the script up at the chest; lap-level props lowered the eyelids (10-27 4b judged unlike).
    assert "举在胸前" in err and "不低头" in err


def test_holding_hint_keeps_doing_prop_at_chest(capsys):
    card = _two_face_card(("close_up", None, "站在沙脊脚下，看向镜头"),
                          ("waist_up", "high", "坐在栈道边，脸朝镜头，双手拿着旧地图，神情专注"))
    sets.validate_set_card(card)
    err = capsys.readouterr().err
    assert "举在胸前" in err and "胸口以下" not in err


def test_second_face_doing_something_has_no_gaze_hint(capsys):
    # Abao r5-3: face toward camera, eyes on what is in her hands, focused, not smiling.
    card = _two_face_card(("close_up", None, "站在沙脊脚下，双手垂在身侧；看向镜头，闭嘴浅笑"),
                          ("waist_up", "high", "坐在栈道边，脸朝镜头，把折着的旧地图举在胸前，眼睛看着地图，不低头，神情专注"))
    sets.validate_set_card(card)
    assert "都看镜头" not in capsys.readouterr().err


def test_negated_camera_gaze_is_not_counted(capsys):
    card = _two_face_card(("close_up", None, "站在沙脊脚下，不看镜头，望着远处"),
                          ("waist_up", "high", "坐在栈道边，看向镜头"))
    sets.validate_set_card(card)
    assert "都看镜头" not in capsys.readouterr().err


def test_changed_look_sets_skip_doing_hint(capsys):
    # D32 tail: opera make-up, headwear or a new hairstyle keeps both face shots on the lens.
    card = _two_face_card(("close_up", None, "站在后台，看向镜头"),
                          ("waist_up", "high", "坐在妆台前，看向镜头"))
    card["shots"][0]["user"]["makeup"] = "京剧旦角淡彩妆"
    sets.validate_set_card(card)
    assert "都看镜头" not in capsys.readouterr().err
    card = _two_face_card(("close_up", None, "站在后台，看向镜头"),
                          ("waist_up", "high", "坐在妆台前，看向镜头"))
    for shot in card["shots"]:
        shot["play_mode"] = "opera_costume"
    sets.check_face_shot_guards(card["shots"])
    assert "都看镜头" not in capsys.readouterr().err


def test_headwear_in_outfit_skips_doing_hint(capsys):
    card = _two_face_card(("close_up", None, "站在洞口，看向镜头"),
                          ("waist_up", "high", "坐在石阶上，看向镜头"))
    for shot in card["shots"]:
        shot["user"]["outfit"] = "红色戏服，头戴凤翅紫金冠，保留本人原有发型和妆容"
    sets.check_face_shot_guards(card["shots"])
    assert "都看镜头" not in capsys.readouterr().err
    for shot in card["shots"]:
        shot["user"]["outfit"] = "奶白亚麻衬衫，不戴帽子"
    sets.check_face_shot_guards(card["shots"])
    assert "都看镜头" in capsys.readouterr().err
