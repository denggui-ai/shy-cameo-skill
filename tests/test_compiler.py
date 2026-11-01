import hashlib
import json
from pathlib import Path

import pytest

from coshoot.cards import CardError, load_json, require_valid
from coshoot.compiler import (CAST_CLOSE_TEXT, CHAIN_TEXT, CHECKIN_TEXT, GENRE_TEXT, SHY_TEXT, SOLO_TEXT, USER_PRESENCE_TEXT,
                              compile_request, hard_constraints, write_request)
from coshoot.names import NameEntry

FIX = Path(__file__).parent / "fixtures" / "cards"
NAMES = [NameEntry("六小龄童", (), None)]


def resolver(asset):
    return Path("/sheets") / (asset["sha256"][:4] + ".png")


def setup():
    scene = load_json(FIX / "scene-shuiliandong.json")
    return scene, {"xiyou/wukong": load_json(FIX / "wukong.json")}


def build(scene=None, chars=None, photos=(Path("/in/me.jpg"),), **kw):
    s, c = setup()
    return compile_request(scene or s, chars or c, list(photos), resolver, NAMES, **kw)


def test_happy_path_refs_and_shy_constraints():
    req = build()
    assert req["referenced_image_paths"] == ["/in/me.jpg", "/sheets/1111.png", "/sheets/2222.png"]
    for line in hard_constraints("classic_presence", True):
        assert line in req["prompt"]
    assert "孙悟空只局部入镜（只露一只手）：侧身递来一只鲜桃" in req["prompt"]
    assert "画面里有主角，以及孙悟空的局部（只露一只手，看不到脸）" in req["prompt"]
    assert "脸宽" not in req["prompt"] and CAST_CLOSE_TEXT in req["prompt"]
    assert "原创设计" not in req["prompt"] and "所有人物是不同的脸" not in req["prompt"]
    assert "附图 2、3 是角色“孙悟空”（美猴王时期）的定妆表，只借露出部分的毛发、衣装与质感" in req["prompt"]
    assert "set" not in req


def test_variant_selection_mhw_has_no_headband():
    assert "紧箍" not in build()["prompt"]


def test_actor_name_in_narrative_is_blocked():
    s, c = setup()
    s["characters"][0]["action"] = "像六小龄童那样递桃"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "blocked_name"


def test_raw_user_utterance_cannot_enter():
    s, c = setup()
    s["user_utterance"] = "随便什么话"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "invalid_scene"


def test_unconfirmed_scene_rejected():
    s, c = setup()
    s["status"] = "unverified"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "scene_not_confirmed"


def test_temp_draft_character_rejected():
    s, c = setup()
    c["xiyou/wukong"]["status"] = "temp_draft"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "character_not_confirmed"


def test_two_characters_keep_available_sheets():
    s, c = setup()
    s["characters"].append({"character_id": "xiyou/wukong", "variant_id": "qujing",
                            "position": "center", "action": "抱臂站立", "character_presence": "back",
                            "visible_parts": "门外远处的背影"})  # without it two identity blurbs pass 760
    req = build(scene=s, chars=c)
    # Every available sheet is kept up to the cap; the user photo always comes first.
    assert req["referenced_image_paths"][:2] == ["/in/me.jpg", "/sheets/1111.png"]
    assert len(req["referenced_image_paths"]) <= 5


@pytest.mark.parametrize("action", [
    "严格背对镜头坐在椅上陪看监视器，不回头。",
    "严格背对镜头原地示范练功起势，不回头。",
    "严格背对镜头走远，不回头。",
])
def test_back_presence_preserves_chosen_action_without_adding_movement(action):
    s, c = setup()
    s["characters"][0].update(character_presence="back", action=action,
                              visible_parts="后脑、耳背与肩背")
    prompt = build(scene=s, chars=c)["prompt"]
    assert action in prompt
    assert prompt.count("走远") == action.count("走远")
    assert "严格背对镜头" in prompt and "不露侧脸" in prompt


def test_f9_trim_order_and_chain_never_dropped():
    photos = [Path("/in/a.jpg"), Path("/in/b.jpg"), Path("/in/c.jpg")]
    chain = Path("/ws/outputs/sets/s1/chain.png")
    full = build(photos=photos, scene_ref=Path("/in/ref.jpg"), chain_ref=chain)
    assert full["referenced_image_paths"] == [
        "/in/a.jpg", "/in/b.jpg", "/sheets/1111.png", "/sheets/2222.png", str(chain)]
    assert build(photos=photos, chain_ref=chain, max_refs=4)["referenced_image_paths"] == [
        "/in/a.jpg", "/in/b.jpg", "/sheets/1111.png", str(chain)]
    assert build(photos=photos, chain_ref=chain, max_refs=3)["referenced_image_paths"] == [
        "/in/a.jpg", "/sheets/1111.png", str(chain)]
    assert build(photos=photos, chain_ref=chain, max_refs=2)["referenced_image_paths"] == [
        "/in/a.jpg", str(chain)]
    with pytest.raises(CardError) as exc:
        build(chain_ref=chain, max_refs=1)
    assert exc.value.code == "too_many_refs"


def test_in_story_requires_role():
    s, c = setup()
    s["user"]["mode"] = "in_story"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "missing_role"


def test_no_user_photo_rejected():
    with pytest.raises(CardError) as exc:
        build(photos=())
    assert exc.value.code == "no_user_photo"


def test_sha_is_stable_and_request_written(tmp_path):
    a = build(run_id="20261010-120000-abcdef")
    b = build(run_id="20261010-120000-abcdef")
    assert a == b
    path = write_request(a, tmp_path / "run")
    assert load_json(path) == a


def test_style_and_aspect_text():
    s, c = setup()
    assert "竖幅 3:4" in build(scene=s, chars=c)["prompt"]
    s["aspect"] = "2:3"
    assert "竖幅 2:3" in build(scene=s, chars=c)["prompt"]


@pytest.mark.parametrize("mode", ["classic_presence", "original_text", "archetype", "genre_scene", "opera_costume", "location_checkin"])
def test_anime_style_is_not_limited_to_original_characters(mode):
    s, c = setup()
    s.update(style="anime", play_mode=mode)
    if mode in ("opera_costume", "location_checkin"):
        s["characters"] = []
    if mode == "opera_costume":
        s["user"]["role"] = "京剧花旦"
    prompt = build(scene=s, chars=c)["prompt"]
    assert "日本电视动画的画面质感" in prompt
    assert "把主角用日式动画画风重绘" in prompt


def test_chain_text_and_set_info():
    chain = Path("/ws/outputs/sets/s1/chain.png")
    req = build(chain_ref=chain, set_info={"set_id": "s1", "index": 2, "role": "wide"})
    assert CHAIN_TEXT.format(n=4, keep="主角的妆发与服装") in req["prompt"]
    assert req["set"] == {"set_id": "s1", "index": 2, "role": "wide"}


def test_sheets_are_optional():
    s, c = setup()
    for variant in c["xiyou/wukong"]["variants"]:
        variant.pop("sheets", None)
    req = build(scene=s, chars=c)
    assert req["referenced_image_paths"] == ["/in/me.jpg"]
    assert "定妆表" not in req["prompt"]


def test_location_can_be_solo_or_with_confirmed_companion():
    s, c = setup()
    s.update(play_mode="location_checkin", characters=[])
    req = build(scene=s, chars=c)
    assert req["referenced_image_paths"] == ["/in/me.jpg"]
    assert SOLO_TEXT in req["prompt"] and SHY_TEXT not in req["prompt"]
    s["characters"] = setup()[0]["characters"]
    prompt = build(scene=s, chars=c)['prompt']
    assert CAST_CLOSE_TEXT in prompt
    assert SOLO_TEXT not in prompt and CHECKIN_TEXT not in prompt


def test_classic_requires_cast():
    s, c = setup()
    s["characters"] = []
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "cast_required"


def test_genre_scene_without_cast_does_not_invent_shy_companion():
    s, c = setup()
    s.update(play_mode="genre_scene", characters=[])
    prompt = build(scene=s, chars=c)["prompt"]
    assert SHY_TEXT not in prompt and SOLO_TEXT in prompt


def test_opera_borrows_face_not_hairstyle():
    s, c = setup()
    s.update(play_mode="opera_costume", characters=[])
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "missing_role"
    s["user"]["role"] = "京剧花旦"
    prompt = build(scene=s, chars=c)["prompt"]
    assert "不借照片里的发型" in prompt
    assert "京剧花旦" in prompt and "五官保持本人可辨" in prompt


FITTING = "额上戴一道金色细箍，头顶戴插两根长雉鸡翎的紫金冠，身披金黄色绣纹战袍"


def test_fitting_names_the_role_and_chain_lists_props():
    s, c = setup()
    s["user"] = {"mode": "fitting", "position": "left", "action": "握着金箍棒，转头正脸看向镜头", "costume": FITTING}
    s["prop_specs"] = [{"name": "金箍棒", "spec": "约一人高、两端金箍、中间乌黑、比拇指略粗"}]
    prompt = build(scene=s, chars=c)["prompt"]
    assert "主角试装成孙悟空" in prompt and FITTING in prompt and "保留自拍中的原有妆面" in prompt
    assert "道具规格：金箍棒——约一人高" in prompt
    s["user"]["role"] = "美猴王"
    chain = Path("/ws/outputs/sets/s1/chain.png")
    prompt = build(scene=s, chars=c, chain_ref=chain,
                   set_info={"set_id": "s1", "index": 3, "role": "interaction"})["prompt"]
    assert "主角试装成美猴王" in prompt
    assert CHAIN_TEXT.format(n=4, keep="主角的妆发与服装") in prompt
    assert "道具规格：金箍棒——约一人高" in prompt  # repeated on every shot that shows it


def test_fitting_rules():
    s,c = setup()
    s['user'] = {'mode':'fitting','position':'left','action':'试装'}
    with pytest.raises(CardError) as exc:
        build(scene=s,chars=c)
    assert exc.value.code == 'missing_costume'
    s['user']['costume'] = FITTING
    s.update(play_mode='location_checkin',characters=[])
    assert FITTING in build(scene=s,chars=c)['prompt']
    s['user']['mode']='in_story'
    s['user']['role']='旅人'
    assert FITTING in build(scene=s,chars=c)['prompt']


def test_character_card_is_never_injected():
    for presence in ("hand", "back", "shadow"):
        s, c = setup()
        s["characters"][0]["character_presence"] = presence
        prompt = build(scene=s, chars=c)["prompt"]
        assert "随身道具" not in prompt and "排除：" not in prompt
    assert "辨识特征" not in prompt  # shadow shows no features


def test_visible_parts_make_one_sentence():
    s, c = setup()
    s["characters"][0].update(visible_parts="一只覆着金黄色猴毛的手", action="从画面右上方伸进来，正帮主角扶正紫金冠")
    prompt = build(scene=s, chars=c)["prompt"]
    assert "孙悟空只局部入镜：一只覆着金黄色猴毛的手，从画面右上方伸进来，正帮主角扶正紫金冠；局部或影子位于画面右侧" in prompt
    assert "头部和躯干在画外" in prompt
    assert "孙悟空的局部（一只覆着金黄色猴毛的手，看不到脸）" in prompt and "辨识特征" not in prompt


@pytest.mark.parametrize("visible_parts", ["金色猴毛手掌与红色袖口前臂", "只有一只手掌，不露前臂"])
def test_hand_presence_keeps_scene_visibility_scope(visible_parts):
    s, c = setup()
    s["characters"][0].update(character_presence="hand", visible_parts=visible_parts)
    prompt = build(scene=s, chars=c)["prompt"]
    assert visible_parts in prompt
    assert "手腕以上在画外" not in prompt
    assert "头部和躯干在画外" in prompt


def test_prompt_stays_close_to_poc_length():
    s, c = setup()
    s["user"] = {"mode": "fitting", "role": "美猴王", "position": "left", "action": "转头正脸看向镜头", "costume": FITTING}
    s["characters"][0]["visible_parts"] = "一只覆着金黄色猴毛的手"
    for variant in c["xiyou/wukong"]["variants"]:
        variant.pop("sheets", None)
    # Includes the shared visible-body/confirmed-change boundary added in 2026-10.
    assert len(build(scene=s, chars=c)["prompt"]) < 900


def test_head_line_lighting_and_film_context():
    s, c = setup()
    prompt = build(scene=s, chars=c)["prompt"]
    assert prompt.startswith("有电影氛围的主题写真，主题语境为经典故事世界中的一次相遇，竖幅")
    s.update(film_context="一部古装神话剧的幕后花絮", lighting="化妆镜四周的灯泡照亮主角的脸")
    prompt = build(scene=s, chars=c)["prompt"]
    assert prompt.startswith("有电影氛围的主题写真，主题语境为一部古装神话剧的幕后花絮，竖幅")
    assert "光线：化妆镜四周的灯泡照亮主角的脸" in prompt


def test_mode_specific_closing_lines():
    s, c = setup()
    s.update(play_mode="location_checkin", characters=[])
    prompt = build(scene=s, chars=c)["prompt"]
    assert prompt.startswith("有摄影设计的旅行写真") and CHECKIN_TEXT in prompt and "电影剧照" not in prompt
    # Solo check-in keeps SOLO_TEXT's faceless passers-by; no contradicting "nobody else" line.
    assert SOLO_TEXT in prompt and "没有其他人" not in prompt and "只有主角一个人物" not in prompt
    s.update(play_mode="genre_scene")
    prompt = build(scene=s, chars=c)["prompt"]
    assert GENRE_TEXT in prompt and CHECKIN_TEXT not in prompt


def test_actor_name_in_new_fields_is_blocked():
    for field, value in (("lighting", "像六小龄童剧里的光"), ("film_context", "六小龄童版")):
        s, c = setup()
        s[field] = value
        with pytest.raises(CardError) as exc:
            build(scene=s, chars=c)
        assert exc.value.code == "blocked_name"


def test_prop_spec_only_when_the_shot_mentions_it():
    s, c = setup()
    s["prop_specs"] = [{"name": "金箍棒", "spec": "两端金箍、中间乌黑"}]
    assert "道具规格" not in build(scene=s, chars=c)["prompt"]
    s["characters"][0]["action"] = "把金箍棒递过来"
    chain = Path("/ws/outputs/sets/s1/chain.png")
    prompt = build(scene=s, chars=c, chain_ref=chain)["prompt"]
    assert "道具规格：金箍棒——两端金箍" in prompt and "主角的妆发与服装、场景" in prompt


def test_chain_does_not_reintroduce_unused_prop_spec(capsys):
    s, c = setup()
    s["prop_specs"] = [{"name": "折伞", "spec": "深绿色伞面，木质弯柄"}]
    prompt = build(scene=s, chars=c, chain_ref=Path("/ws/chain.png"),
                   chain_props=["折伞"])["prompt"]
    assert "折伞" not in prompt
    assert "折伞" in capsys.readouterr().err


def test_current_prop_state_survives_chain_reference():
    s, c = setup()
    s["prop_specs"] = [{"name": "折伞", "spec": "一把深绿色折伞，已收拢扣带，由主角持有"}]
    s["user"]["action"] = "手握折伞的弯柄"
    prompt = build(scene=s, chars=c, chain_ref=Path("/ws/chain.png"),
                   chain_props=["折伞"])["prompt"]
    assert "道具规格：折伞——一把深绿色折伞，已收拢扣带，由主角持有" in prompt


def test_scene_printed_page_is_not_contradicted_by_global_no_text():
    s, c = setup()
    s["props"] = "桌上一本印刷书，页内印刷行不可辨读，不要求精确排字"
    prompt = build(scene=s, chars=c)["prompt"]
    assert "无文字" not in prompt
    assert "场内必要的印刷或手写痕迹" in prompt


def test_prop_spec_from_pet_action_is_preserved():
    s, c = setup()
    s["pet"] = "在主角右前方宽地毯上用前爪拨弄毛线球"
    s["prop_specs"] = [{"name": "毛线球", "spec": "一枚掌心大小的低饱和苔绿色粗毛线球"}]
    assert "道具规格：毛线球——一枚掌心大小的低饱和苔绿色粗毛线球" in build(
        scene=s, chars=c, pet={"kind": "猫", "ref": Path("/in/cat.jpg")})["prompt"]


@pytest.mark.parametrize("field", ["hairstyle", "makeup"])
def test_prop_spec_in_rendered_user_detail_is_preserved(field):
    s, c = setup()
    s["user"][field] = "保留原有造型，加入一根发簪"
    s["prop_specs"] = [{"name": "发簪", "spec": "深棕木质，细长无坠饰"}]
    assert "道具规格：发簪——深棕木质，细长无坠饰" in build(scene=s, chars=c)["prompt"]


def test_props_on_image_1_keep_current_shot_spec():
    s, c = setup()
    s["prop_specs"] = [{"name": "金箍棒", "spec": "两端金箍、中间乌黑"}]
    s["characters"][0]["action"] = "把金箍棒递过来"
    chain = Path("/ws/outputs/sets/s1/chain.png")
    prompt = build(scene=s, chars=c, chain_ref=chain, chain_props=["金箍棒"])["prompt"]
    assert CHAIN_TEXT.format(n=4, keep="主角的妆发与服装、金箍棒") in prompt
    assert "道具规格：金箍棒——两端金箍、中间乌黑" in prompt
    prompt = build(scene=s, chars=c, chain_ref=chain, chain_props=[])["prompt"]
    assert "道具规格：金箍棒" in prompt and CHAIN_TEXT.format(n=4, keep="主角的妆发与服装") in prompt


def test_familiar_animation_design_is_not_a_blanket_refusal():
    prompt = build()["prompt"]
    assert "不复刻动画或游戏的角色设计" not in prompt
    assert CAST_CLOSE_TEXT in prompt


def test_original_text_mode_keeps_the_no_adaptation_line():
    # codex-review ebc81ca: "回到原著" must still forbid screen-version looks.
    from coshoot.compiler import ADAPTATION_TEXT, ORIGINAL_TEXT_ADAPTATION, hard_constraints
    assert ORIGINAL_TEXT_ADAPTATION in hard_constraints("original_text", True)
    assert ADAPTATION_TEXT not in hard_constraints("original_text", True)
    assert ADAPTATION_TEXT in hard_constraints("classic_presence", True)


def test_cast_prompts_forbid_adaptation_looks_and_archetype_keeps_exclusions():
    from coshoot.compiler import ADAPTATION_TEXT
    s, c = setup()
    assert ADAPTATION_TEXT in build(scene=s, chars=c)["prompt"]
    c["xiyou/wukong"]["variants"][0]["exclusions"] = "无村落标志"
    for v in c["xiyou/wukong"]["variants"]:
        v["exclusions"] = "无村落标志"
    s["play_mode"] = "archetype"
    assert "排除：无村落标志" in build(scene=s, chars=c)["prompt"]


def test_every_presence_states_its_no_face_mechanism():
    from coshoot.compiler import NO_FACE_MECHANISM
    for presence in ("hand", "shadow", "back", "cropped", "peek"):
        s, c = setup()
        s["characters"][0]["character_presence"] = presence
        assert NO_FACE_MECHANISM[presence] in build(scene=s, chars=c)["prompt"], presence


def test_side_profile_is_retired_with_a_hint():
    s, c = setup()
    s["characters"][0]["character_presence"] = "side_profile"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "presence_retired" and "back" in exc.value.message


def test_costume_keys_named_in_chain_line():
    s, c = setup()
    s["characters"][0]["action"] = "把金箍棒递过来"
    s["prop_specs"] = [{"name": "金箍棒", "spec": "两端金箍、中间乌黑"}]
    chain = Path("/ws/outputs/sets/s1/chain.png")
    keys = ["金箍", "紫金冠与雉鸡翎", "虎皮裙"]
    s["user"]["costume_keys"] = keys
    prompt = build(scene=s, chars=c, chain_ref=chain)["prompt"]
    assert CHAIN_TEXT.format(n=4, keep="主角的妆发与服装（金箍、紫金冠与雉鸡翎、虎皮裙）") in prompt
    prompt = build(scene=s, chars=c, chain_ref=chain, chain_props=["金箍棒"])["prompt"]
    assert CHAIN_TEXT.format(n=4, keep="主角的妆发与服装（金箍、紫金冠与雉鸡翎、虎皮裙）、金箍棒") in prompt
    assert "金箍、紫金冠与雉鸡翎" not in build(scene=s, chars=c)["prompt"]  # image 1 has no chain line


def test_costume_keys_schema_limits():
    for keys in ([], ["a", "b", "c", "d", "e", "f"], ["a", "b", "x" * 13]):
        s, c = setup()
        s["user"]["costume_keys"] = keys
        with pytest.raises(CardError) as exc:
            build(scene=s, chars=c)
        assert exc.value.code == "invalid_scene", keys


def _size(prompt):
    return len("".join(prompt.split()))


def test_prompt_length_760_is_advisory_and_preserves_integrity(capsys, monkeypatch):
    s, c = setup()
    # Isolate length-warning behavior from growth of independently tested style text.
    monkeypatch.setattr('coshoot.compiler.style_text', lambda scene: '写真。')
    base = _size(build(scene=s, chars=c)["prompt"]) - len(s["setting"])
    s["setting"] = "木" * (760 - base)
    assert _size(build(scene=s, chars=c)["prompt"]) == 760
    assert capsys.readouterr().err == ""
    s["setting"] += "木"
    request = build(scene=s, chars=c, set_info={"set_id": "s1", "index": 1, "role": "cover"})
    assert _size(request["prompt"]) == 761 and s["setting"] in request["prompt"]
    notice = capsys.readouterr().err
    assert "第 1 张" in notice and "761" in notice and "建议" in notice
    require_valid(request, "request")
    body = {"prompt": request["prompt"], "referenced_image_paths": request["referenced_image_paths"]}
    expected = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert request["sha256"] == expected


def test_cover_has_two_levels_and_needs_one():
    from coshoot.compiler import COVER_MECHANISM
    s, c = setup()
    s["characters"][0].update(character_presence="cover", visible_parts="举着一大丛带叶桃枝的双手")
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "cover_level_required"
    for level in ("full_head", "face"):
        s["characters"][0]["cover_level"] = level
        prompt = build(scene=s, chars=c)["prompt"]
        assert COVER_MECHANISM[level] in prompt and "藏在" in COVER_MECHANISM[level]
    s["characters"][0].update(character_presence="hand")
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "cover_level_only_for_cover"


def test_malformed_presence_is_a_schema_error_not_a_crash():
    s, c = setup()
    s["characters"][0]["character_presence"] = []
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "invalid_scene"


def test_no_face_features_injected_without_visible_parts():
    # identity_features describe the face; a no-face presence must not be told to match them.
    for presence in ("hand", "back", "cropped", "peek", "cover"):
        s, c = setup()
        s["characters"][0]["character_presence"] = presence
        if presence == "cover":
            s["characters"][0]["cover_level"] = "face"
        prompt = build(scene=s, chars=c)["prompt"]
        assert "辨识特征" not in prompt, presence
        assert c["xiyou/wukong"]["variants"][0]["identity_features"] not in prompt, presence


def test_cover_head_label_matches_two_levels():
    from coshoot.compiler import PRESENCE_TEXT
    assert PRESENCE_TEXT["cover"] == "用道具遮住脸"


def test_face_line_allows_three_quarter_view():
    from coshoot.compiler import FACE_TEXT
    for text in (CAST_CLOSE_TEXT, FACE_TEXT):
        assert "正脸清楚受光" not in text and "四分之三侧脸" in text and "五官完整可见" in text


def test_close_up_framing_and_camera_angle():
    s, c = setup()
    s["framing"] = "close_up"
    s["camera_angle"] = "low"
    prompt = build(scene=s, chars=c)["prompt"]
    assert "构图：头肩近景" in prompt and "机位：略仰拍" in prompt
    s["camera_angle"] = "overhead"
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "invalid_scene"


def test_face_cover_allows_but_does_not_force_the_crown():
    # Runs 114-118: a low headscarf (Zhuge Liang) need not peek; the card's visible_parts decides.
    from coshoot.compiler import COVER_MECHANISM
    text = COVER_MECHANISM["face"]
    assert "可露在道具上方" in text and "只从边缘探出" not in text and "这截头饰" not in text
    s, c = setup()
    s["characters"][0].update(character_presence="cover", cover_level="face",
                              visible_parts="只露手、袖口和羽扇，不露纶巾顶")
    prompt = build(scene=s, chars=c)["prompt"]
    assert "不露纶巾顶" in prompt and "探出" not in prompt


def test_shadow_is_anchored_life_size_near_the_user():
    # Run 110: a giant shadow floated on a far backdrop above the ship models, no light source.
    from coshoot.compiler import NO_FACE_MECHANISM
    text = NO_FACE_MECHANISM["shadow"]
    assert "附近" in text and "等大" in text and "光源" in text and "没有面部细节" in text


def test_fitting_styling_restyles_hair_and_allows_light_makeup():
    # Optional styling must remain separate from the default identity-preserving path.
    s, c = setup()
    s["user"] = {"mode": "fitting", "role": "林黛玉", "position": "left", "action": "低头看花", "costume": FITTING}
    plain = build(scene=s, chars=c)["prompt"]
    assert "保留自拍中的原有妆面，不另加角色妆" in plain and "保留主角原有发型轮廓" in plain
    assert "身份参考采用主角的脸、发型" in plain and "未说明时沿用自拍表情" in plain
    s["user"].update(hairstyle="乌发挽成低垂的发髻，鬓边一支素银簪", makeup="细长淡眉、浅色唇")
    prompt = build(scene=s, chars=c)["prompt"]
    assert "细长淡眉、浅色唇" in prompt and "乌发挽成低垂的发髻，鬓边一支素银簪" in prompt
    assert "脸部身份参考采用主角的脸，不借照片里的发型、衣服" in prompt and "原有发型" not in prompt


@pytest.mark.parametrize("field,value", [
    ("hairstyle", "乌发向后梳理，侧鬓贴戴细银钗与小花簪，珠饰收在头发轮廓内；" * 3),
    ("makeup", "淡眉、自然眼线、浅粉唇，底妆保留皮肤细节，不修窄脸型；" * 3),
])
def test_long_styling_descriptions_compile_without_truncation(field, value):
    s, c = setup()
    s["user"] = {"mode": "fitting", "position": "left", "action": "接桃", "costume": FITTING, field: value}
    assert value in build(scene=s, chars=c)["prompt"]


@pytest.mark.parametrize("field", ["hairstyle", "makeup"])
@pytest.mark.parametrize("value", ["", 42])
def test_styling_still_requires_nonempty_strings(field, value):
    s, c = setup()
    s["user"] = {"mode": "fitting", "position": "left", "action": "接桃", "costume": FITTING, field: value}
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "invalid_scene"


@pytest.mark.parametrize("field", ["hairstyle", "makeup"])
def test_actor_names_at_end_of_long_styling_are_still_blocked(field):
    s, c = setup()
    s["user"] = {"mode": "fitting", "position": "left", "action": "接桃", "costume": FITTING,
                 field: "自然轮廓与细节，" * 100 + "六小龄童"}
    with pytest.raises(CardError) as exc:
        build(scene=s, chars=c)
    assert exc.value.code == "blocked_name"


@pytest.mark.parametrize("mode,style,hairstyle", [
    ("classic_presence", "realistic", None),
    ("classic_presence", "realistic", "高马尾"),
    ("archetype", "anime", None),
    ("archetype", "anime", "高马尾"),
    ("opera_costume", "realistic", None),
])
def test_photo_expression_is_conditional_in_every_route(mode, style, hairstyle):
    s, c = setup()
    s.update(play_mode=mode, style=style)
    s["user"] = {"mode": "fitting", "position": "left", "action": "接过鲜桃，眯眼笑", "costume": FITTING}
    if hairstyle:
        s["user"]["hairstyle"] = hairstyle
    if mode == "opera_costume":
        s["characters"] = []
        s["user"] = {"mode": "in_story", "position": "left", "role": "京剧花旦", "action": "回眸，眯眼笑"}
    prompt = build(scene=s, chars=c)["prompt"]
    photo_line = prompt.splitlines()[1]
    assert "表情按本张动作中的明确描述执行，未说明时沿用自拍表情" in photo_line
    assert "原有表情" not in photo_line and "不因表情改变脸型和五官骨相" in photo_line
    assert s["user"]["action"] in prompt


def test_fitting_styling_rules():
    s, c = setup()
    s["user"] = {"mode": "fitting", "role": "美猴王", "position": "left", "action": "笑", "costume": FITTING,
                 "makeup": "画上猴妆和浓妆"}
    assert "猴妆和浓妆" in build(scene=s, chars=c)["prompt"]
    # A requested makeup look may be described;
    # only face-covering paint, prosthetics and effects makeup stay blocked, to keep the user's own face.
    s["user"]["makeup"] = "照古装定妆的浓妆：罥烟眉、眼尾晕染、正红唇色"
    assert "眼尾晕染" in build(scene=s, chars=c)["prompt"]
    s["user"] = {"mode": "traveler", "position": "left", "action": "笑", "hairstyle": "高马尾"}
    assert "高马尾" in build(scene=s, chars=c)["prompt"]


def test_styling_review_cases():
    s, c = setup()
    s["user"] = {"mode": "fitting", "role": "美猴王", "position": "left", "action": "笑", "costume": FITTING,
                 "makeup": "细长淡眉、浅色唇，不画浓妆"}
    assert "不画浓妆" in build(scene=s, chars=c)["prompt"]
    s["user"]["makeup"] = "淡眉淡唇，不用脸谱和特效妆"
    build(scene=s, chars=c)
    s["user"]["makeup"] = "淡眉淡唇，不画浓妆、脸谱或特效妆"
    build(scene=s, chars=c)
    s["user"]["makeup"] = "淡眉，浓妆红唇"
    build(scene=s, chars=c)  # imitating a heavy screen look is allowed
    s["user"]["makeup"] = "淡眉，特效妆"
    assert "特效妆" in build(scene=s, chars=c)["prompt"]
    s["user"]["makeup"] = "淡眉"
    s.update(play_mode="archetype", style="anime")
    s["user"]["hairstyle"] = "高马尾"
    prompt = build(scene=s, chars=c)["prompt"]
    assert "发型：高马尾" in prompt and "发型与原有表情" not in prompt



def test_prop_name_mismatch_warns_and_canonical_name_preserves_spec(capsys):
    s, c = setup()
    s['prop_specs'] = [{'name': '酒葫芦', 'spec': '赭黄双腹，短颈木塞'}]
    s['user']['action'] = '双手接住葫芦'
    prompt = build(scene=s, chars=c)['prompt']
    assert '道具规格：酒葫芦' not in prompt
    assert '酒葫芦' in capsys.readouterr().err
    s['user']['action'] = '双手接住酒葫芦'
    assert '道具规格：酒葫芦——赭黄双腹，短颈木塞' in build(scene=s, chars=c)['prompt']


def test_cover_preserves_chosen_column_without_adding_door_or_curtain():
    s, c = setup()
    s['setting'] = '杏黄墙和原位木柱'
    s['characters'][0].update(character_presence='cover', cover_level='full_head',
                               action='身体藏在原有木柱后，自己举密实大蒲扇遮住整个头部',
                               visible_parts='手、袖口和蒲扇')
    prompt = build(scene=s, chars=c)['prompt']
    assert '木柱' in prompt and '门框' not in prompt and '帐幕' not in prompt
    assert '头顶、头发、双耳、两侧和下巴都在道具后' in prompt


def test_classic_portrait_keeps_identity_without_documentary_defaults():
    s, c = setup()
    prompt = build(scene=s, chars=c)['prompt']
    assert '主题写真' in prompt and '主角优先' in prompt
    assert '不瘦脸' in prompt and '不放大眼睛' in prompt and '角色绝不露脸' in prompt
    assert '胶片颗粒' not in prompt and '允许不完美' not in prompt
    s['film_context'] = '现代剧组拍摄古装故事的后台探班'
    assert '现代剧组拍摄古装故事的后台探班' in build(scene=s, chars=c)['prompt']


def test_portrait_default_does_not_replace_other_modes():
    from coshoot.compiler import style_text
    s, _ = setup()
    for mode in ['original_text','genre_scene','opera_costume','archetype']:
        s['play_mode'] = mode
        assert style_text(s).startswith('电影剧照质感')
    s['play_mode'] = 'location_checkin'
    assert style_text(s).startswith('有摄影设计的旅行写真')
    assert '打卡照' not in style_text(s) and '允许不完美' not in style_text(s)
    s.update(play_mode='archetype',style='anime')
    assert style_text(s).startswith('日本电视动画')


@pytest.mark.parametrize('visual', [
    {'subject': 'photographic', 'environment': 'photographic', 'characters': 'animation_3d'},
    {'subject': 'photographic', 'environment': 'animation_3d'},
    {'subject': 'animation_2d', 'environment': 'animation_2d'},
])
def test_visual_branch_carries_photography_direction(visual):
    # D17: the real-plus-animation branch used to carry no photography direction at all.
    from coshoot.compiler import style_text, VISUAL_CRAFT_TEXT
    s, _ = setup()
    s['visual'] = visual
    text = style_text(s)
    assert VISUAL_CRAFT_TEXT in text and '主角优先' in text and '摄影设计' in text
    assert text.startswith('竖幅')


def test_photographic_visual_branch_carries_low_key_film_light():
    # D30: "film still" alone drifted into bright ad/travel looks; animated environments and check-ins keep their own light.
    from coshoot.compiler import style_text, FILM_LIGHT_TEXT
    s, _ = setup()
    s['visual'] = {'subject': 'photographic', 'environment': 'photographic', 'characters': 'animation_3d'}
    assert FILM_LIGHT_TEXT in style_text(s) and '胶片颗粒' not in style_text(s)
    s['visual'] = {'subject': 'animation_2d', 'environment': 'animation_2d'}
    assert FILM_LIGHT_TEXT not in style_text(s)
    s['visual'] = {'subject': 'photographic', 'environment': 'photographic'}
    s['play_mode'] = 'location_checkin'
    assert FILM_LIGHT_TEXT not in style_text(s)
    s['play_mode'] = 'classic_presence'
    assert FILM_LIGHT_TEXT in style_text(s)
    s['lighting'] = '用户指定明亮日景，上午侧向阳光照亮主角，树荫保留暗部'
    assert FILM_LIGHT_TEXT not in style_text(s)


@pytest.mark.parametrize('mode', ['original_text', 'opera_costume', 'genre_scene', 'location_checkin'])
@pytest.mark.parametrize('with_cast', [False, True])
def test_optional_companions_follow_actual_cast(mode, with_cast):
    from coshoot.compiler import ORIGINAL_TEXT_ADAPTATION
    scene, chars = setup()
    scene['play_mode'] = mode
    if not with_cast:
        scene['characters'] = []
    if mode == 'opera_costume':
        scene['user']['role'] = '京剧花旦'
    prompt = build(scene=scene, chars=chars)['prompt']
    assert (CAST_CLOSE_TEXT in prompt) == with_cast
    assert (SOLO_TEXT in prompt) == (not with_cast)
    if mode == 'original_text':
        assert ORIGINAL_TEXT_ADAPTATION in prompt
    if mode == 'location_checkin' and with_cast:
        assert '没有任何动漫' not in prompt


@pytest.mark.parametrize("presence", ["back", "hands"])
def test_faceless_user_presence_drops_face_visible_line(presence):
    scene, _ = setup()
    scene["user"]["presence"] = presence
    require_valid(scene, "scene")
    prompt = build(scene=scene)["prompt"]
    assert "五官完整可见" not in prompt
    assert USER_PRESENCE_TEXT[presence] in prompt
    assert "主角不长出角色五官，不混脸" in prompt and "角色绝不露脸" in prompt
    solo = dict(scene, characters=[])
    assert "五官完整可见" not in "".join(hard_constraints("classic_presence", False, scene=solo))


def test_back_user_presence_allows_a_shoulder_line_look_back():
    # D25: faceless shots move freely; a look-back stops at the shoulder line, no profile.
    text = USER_PRESENCE_TEXT["back"]
    assert "回头最多转到肩线" in text and "不露侧脸" in text and "不回头" not in text


def test_default_user_presence_keeps_face_line():
    assert CAST_CLOSE_TEXT in build()["prompt"]


@pytest.mark.parametrize('variant', ['face', 'back', 'hands', 'restyled', 'anime', 'opera'])
def test_body_reference_scope_and_explicit_adjustment_reach_request(variant):
    scene, _ = setup()
    scene['user']['action'] = ('自然站立；已确认肩髋接近、腰线较平直；'
                               '本次只调整腰部，胸臀体量保留；身高未知')
    scene['user']['outfit'] = '白色合身上衣；支撑效果自然，不额外聚拢'
    if variant in ('back', 'hands'):
        scene['user']['presence'] = variant
    elif variant == 'restyled':
        scene['user']['hairstyle'] = '短发'
    elif variant == 'anime':
        scene['style'] = 'anime'
    elif variant == 'opera':
        scene['play_mode'] = 'opera_costume'
        scene['user']['role'] = '闺门旦'
    prompt = build(scene=scene, chain_ref=Path('/ws/prior.png'))['prompt']
    assert scene['user']['action'] in prompt
    assert scene['user']['outfit'] in prompt
    assert '清楚可见或本张描述已确认' in prompt
    assert '不推断遮挡、未入镜部位或衣下尺寸' in prompt
    assert '明确调整仅覆盖对应部位' in prompt
    assert '服装支撑、姿势与镜头造成的外观变化不等于身体改变' in prompt
    assert '只借主角的脸' not in prompt
    assert '发色、肤色与体型' not in prompt


@pytest.mark.parametrize("presence,framing", [("hands", "close_up"), ("hands", "waist_up"), ("back", "close_up")])
def test_faceless_presence_never_asks_for_face_sized_framing(presence, framing):
    scene, _ = setup()
    scene["user"].update(presence=presence, action="双手剥开桃子")
    scene["framing"] = framing
    prompt = build(scene=scene)["prompt"]
    assert "脸占画面" not in prompt and "五官完整可见" not in prompt


def test_faceless_presence_rejects_side_camera_but_allows_opera():
    scene, _ = setup()
    scene["user"]["presence"] = "back"
    scene["camera_angle"] = "side"
    with pytest.raises(CardError) as e:
        build(scene=scene)
    assert e.value.code == "presence_camera_conflict"
    scene.pop("camera_angle")
    scene.update(play_mode="opera_costume")
    scene["user"]["role"] = "闺门旦"
    prompt = build(scene=scene)["prompt"]
    assert "闺门旦的戏曲扮相" in prompt and "头面与戏服完整" not in prompt and "五官保持本人可辨" not in prompt
    scene["user"]["presence"] = "hands"
    prompt = build(scene=scene)["prompt"]
    assert "可见袖口按本张衣装说明呈现" in prompt and "水袖" not in prompt and "头面" not in prompt and "五官保持本人可辨" not in prompt


@pytest.mark.parametrize("presence,framing", [("back", "full_body"), ("hands", "close_up")])
def test_opera_preparation_respects_current_clothing(presence, framing):
    scene, _ = setup()
    scene.update(play_mode="opera_costume", characters=[], framing=framing)
    scene["user"].update(mode="fitting", role="原创旦角造型", presence=presence,
                         outfit="仅穿素灰准备服，红色演出袍尚未穿上，头冠仍放在桌上",
                         action="背对镜头整理挂着的演出袍" if presence == "back" else "只拍准备服袖口与整理挂袍的手")
    prompt = build(scene=scene, chain_ref=Path("/ws/preparation.png"))["prompt"]
    assert scene["user"]["outfit"] in prompt
    assert "/ws/preparation.png" in build(scene=scene, chain_ref=Path("/ws/preparation.png"))["referenced_image_paths"]
    assert "头面与戏服完整" not in prompt
    assert "手部可见本套戏服的袖口" not in prompt
    assert "不画出主角的五官" in prompt


@pytest.mark.parametrize("presence", ["back", "hands"])
def test_faceless_presence_drops_face_expression_and_chain_face_lines(presence):
    scene, _ = setup()
    scene["user"].update(presence=presence, action="背对镜头走上石阶")
    prompt = build(scene=scene, chain_ref=Path("/ws/chain.png"))["prompt"]
    for phrase in ("脸型、眼形", "自拍表情", "主角的脸以附图 1 为准", "五官完整可见", "脸占画面"):
        assert phrase not in prompt, phrase
    assert "不画出主角的五官" in prompt and "主角不露脸" in prompt



@pytest.mark.parametrize('case', ['classic', 'original', 'anime', 'checkin', 'visual_photo', 'visual_bright', 'visual_anim'])
def test_every_style_branch_carries_cinema_quality(case):
    # Owner 2026-10-26: every image must look like a film frame; the low-key D30 light keeps its own conditions.
    from coshoot.compiler import style_text, CINEMA_TEXT, CINEMA_ANIM_TEXT, FILM_LIGHT_TEXT
    s, _ = setup()
    s.pop('visual', None)
    if case == 'original':
        s['play_mode'] = 'original_text'
    elif case == 'anime':
        s['style'] = 'anime'
    elif case == 'checkin':
        s.update(play_mode='location_checkin', characters=[])
    elif case.startswith('visual'):
        anim = case == 'visual_anim'
        s['visual'] = ({'subject': 'animation_2d', 'environment': 'animation_2d'} if anim
                       else {'subject': 'photographic', 'environment': 'photographic'})
        if case == 'visual_bright':
            s['lighting'] = '明亮日景，上午侧向阳光照亮主角，树荫保留暗部'
    text = style_text(s)
    if case in ('anime', 'visual_anim'):
        assert CINEMA_ANIM_TEXT in text and CINEMA_TEXT not in text
    else:
        assert CINEMA_TEXT in text
    if case == 'visual_bright':
        assert FILM_LIGHT_TEXT not in text


def test_mood_ref_borrows_light_and_tone_before_chain():
    req = build(mood_ref=Path("/in/mood.jpg"), chain_ref=Path("/sets/chain.png"))
    refs = req["referenced_image_paths"]
    assert refs[-2:] == ["/in/mood.jpg", "/sets/chain.png"]
    assert "附图 4 是氛围参考，只借光线方向、明暗和色调；不借构图、景别和机位，不借其中的人物、文字、标志和具体物件。" in req["prompt"]


def test_scene_ref_excludes_text_and_logos():
    assert "只借环境与光线，不借其中的任何人物、文字和标志。" in build(scene_ref=Path("/in/place.jpg"))["prompt"]


def test_mood_ref_outranks_body_sheet_in_budget(capsys):
    kw = dict(scene_ref=Path("/in/place.jpg"), mood_ref=Path("/in/mood.jpg"), chain_ref=Path("/sets/chain.png"))
    assert build(max_refs=5, **kw)["referenced_image_paths"] == [
        "/in/me.jpg", "/sheets/1111.png", "/sheets/2222.png", "/in/mood.jpg", "/sets/chain.png"]
    assert build(max_refs=4, **kw)["referenced_image_paths"] == [
        "/in/me.jpg", "/sheets/1111.png", "/in/mood.jpg", "/sets/chain.png"]
    capsys.readouterr()
    assert "/in/mood.jpg" not in build(max_refs=3, **kw)["referenced_image_paths"]
    assert "未采用氛围参考图：/in/mood.jpg" in capsys.readouterr().err


@pytest.mark.parametrize('branch', ['visual', 'legacy'])
def test_checkin_gets_travel_film_light_and_face_light(branch):
    # Owner 10-28: a check-in cover read as a phone snapshot; travel gets its own film light that does not darken daytime.
    from coshoot.compiler import style_text, CHECKIN_FILM_LIGHT_TEXT, FACE_LIGHT_TEXT, FILM_LIGHT_TEXT
    s, _ = setup()
    s.update(play_mode='location_checkin', characters=[])
    if branch == 'legacy':
        s.pop('visual', None)
    else:
        s['visual'] = {'subject': 'photographic', 'environment': 'photographic'}
    text = style_text(s)
    assert CHECKIN_FILM_LIGHT_TEXT in text and FACE_LIGHT_TEXT in text and FILM_LIGHT_TEXT not in text
    s['lighting'] = '明亮日景，上午侧向阳光照亮主角'
    text = style_text(s)
    assert CHECKIN_FILM_LIGHT_TEXT not in text and FACE_LIGHT_TEXT in text


def test_face_light_only_on_photographic_face_shots():
    from coshoot.compiler import style_text, FACE_LIGHT_TEXT, FILM_LIGHT_TEXT
    s, _ = setup()
    s['visual'] = {'subject': 'photographic', 'environment': 'photographic'}
    assert FILM_LIGHT_TEXT + FACE_LIGHT_TEXT in style_text(s)
    s['user'] = dict(s['user'], presence='back')
    assert FACE_LIGHT_TEXT not in style_text(s)
    s['user']['presence'] = 'face'
    s['visual'] = {'subject': 'animation_2d', 'environment': 'animation_2d'}
    assert FACE_LIGHT_TEXT not in style_text(s)


def test_face_light_never_splits_the_face():
    # lessons 34: half the face in shadow read as someone else.
    from coshoot.compiler import FACE_LIGHT_TEXT
    for bad in ('暗一档', '半张脸', '均匀'):
        assert bad not in FACE_LIGHT_TEXT
    assert '眼神光' in FACE_LIGHT_TEXT and '不切明暗' in FACE_LIGHT_TEXT


def test_travel_light_names_one_key_source_and_face_follows_it():
    # Owner 10-28 night cover: four competing light sources and a flash-lit face had no depth.
    from coshoot.compiler import CHECKIN_FILM_LIGHT_TEXT, FACE_LIGHT_TEXT
    assert '只认一个主光源' in CHECKIN_FILM_LIGHT_TEXT and '暗部占画面一半以上' in CHECKIN_FILM_LIGHT_TEXT
    assert '来自画面里那个主光源' in FACE_LIGHT_TEXT and '不像闪光灯' in FACE_LIGHT_TEXT


PET = {"ref": Path("/in/cat.jpg"), "kind": "猫"}


def _pet_scene(action="蹲在主角脚边，抬头看远处"):
    s, _ = setup()
    if action:
        s["pet"] = action
    return s


def test_pet_rides_after_mood_before_chain():
    req = build(scene=_pet_scene(), pet=PET, mood_ref=Path("/in/mood.jpg"), chain_ref=Path("/sets/chain.png"),
                max_refs=6)
    assert req["referenced_image_paths"][-3:] == ["/in/mood.jpg", "/in/cat.jpg", "/sets/chain.png"]
    assert "附图 5 是主角自己的猫：画面里的猫就是它" in req["prompt"]
    assert "猫在这张里：蹲在主角脚边，抬头看远处。" in req["prompt"]
    assert "按本张画风画它" not in req["prompt"]


def test_pet_is_never_dropped_from_budget():
    kw = dict(scene=_pet_scene(), pet=PET, chain_ref=Path("/sets/chain.png"),
              photos=(Path("/in/me.jpg"), Path("/in/me2.jpg")))
    assert build(max_refs=5, **kw)["referenced_image_paths"] == [
        "/in/me.jpg", "/in/me2.jpg", "/sheets/1111.png", "/in/cat.jpg", "/sets/chain.png"]
    assert build(max_refs=4, **kw)["referenced_image_paths"] == [
        "/in/me.jpg", "/sheets/1111.png", "/in/cat.jpg", "/sets/chain.png"]
    with pytest.raises(CardError) as e:
        build(max_refs=2, **kw)
    assert e.value.code == "too_many_refs" and "宠物照" in str(e.value)


def test_pet_shot_needs_set_pet_and_cover_needs_pet():
    with pytest.raises(CardError) as e:
        build(scene=_pet_scene())
    assert e.value.code == "pet_without_ref"
    cover = {"set_id": "s1", "index": 1, "role": "cover"}
    with pytest.raises(CardError) as e:
        build(scene=_pet_scene(None), pet=PET, set_info=cover)
    assert e.value.code == "pet_missing_on_cover"
    assert "/in/cat.jpg" in build(scene=_pet_scene(), pet=PET, set_info=cover)["referenced_image_paths"]


def test_shot_without_pet_skips_photo_and_says_no_pet():
    req = build(scene=_pet_scene(None), pet=PET, chain_ref=Path("/sets/chain.png"),
                set_info={"set_id": "s1", "index": 3, "role": "shy"})
    assert "/in/cat.jpg" not in req["referenced_image_paths"]
    assert "这张画面里没有猫，不要从附图 4 带出猫。" in req["prompt"]


def test_pet_in_anime_keeps_coat():
    s = _pet_scene()
    s.update(play_mode="archetype", style="anime")
    assert "按本张画风画它，但毛色花纹和眼睛颜色不变。" in build(scene=s, pet=PET)["prompt"]


def _daily(action="窝在她怀里", **kw):
    s, c = setup()
    s.update(play_mode="pet_daily", characters=[], **kw)
    if action:
        s["pet"] = action
    return s, c


def test_pet_daily_is_home_life_not_travel():
    s, c = _daily()
    prompt = build(scene=s, chars=c, pet=PET)["prompt"]
    for text in ("有摄影设计的生活写真", "生活电影布光", "脸部光", "主角在自己的日常生活里，和自己的猫在一起。", CHECKIN_TEXT):
        assert text in prompt, text
    for text in ("旅行写真", "旅行电影布光", "来访者"):
        assert text not in prompt, text


def test_pet_daily_rules():
    s, c = _daily()
    s["characters"] = setup()[0]["characters"]
    with pytest.raises(CardError) as e:
        build(scene=s, chars=c, pet=PET)
    assert e.value.code == "pet_daily_no_cast"
    s, c = _daily()
    with pytest.raises(CardError) as e:
        build(scene=s, chars=c)
    assert e.value.code == "pet_daily_needs_pet"
    s, c = _daily(None)
    with pytest.raises(CardError) as e:
        build(scene=s, chars=c, pet=PET, set_info={"set_id": "d1", "index": 3, "role": "shy"})
    assert e.value.code == "pet_daily_every_shot"


def test_pet_daily_visual_branch_keeps_daily_light():
    s, c = _daily(visual={"subject": "photographic", "environment": "photographic"})
    prompt = build(scene=s, chars=c, pet=PET)["prompt"]
    assert "生活电影布光" in prompt and "和自家宠物在一起的一件日常小事" in prompt
    assert "旅行电影布光" not in prompt and "电影布光：光有明确方向" not in prompt


def test_pet_look_names_breed_and_build():
    look = dict(PET, look="英短金渐层，圆脸大眼、身子圆滚滚、短腿")
    assert "画面里的猫就是它，它是英短金渐层，圆脸大眼、身子圆滚滚、短腿，毛色" in build(
        scene=_pet_scene(), pet=look)["prompt"]
    assert "画面里的猫就是它，毛色" in build(scene=_pet_scene(), pet=PET)["prompt"]
