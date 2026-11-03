"""Concert routes: synthetic cards and images only; no provider or model calls."""
import copy
import json
from pathlib import Path

import pytest

from coshoot import sets
from coshoot.cards import CardError, require_valid
from coshoot.compiler import (CAST_HIDDEN_TEXT, CHECKIN_TEXT, FACE_LIGHT_TEXT, FACE_TEXT, FILM_LIGHT_TEXT, MY_STAGE_TEXT,
                              SOLO_TEXT, STAGE_FACE_TEXT, STAGE_LIGHT_TEXT, USER_PRESENCE_TEXT)
from test_cli import FAKE, cli, fake_env
from test_cli_sets import set_workspace
from test_compiler import build, setup


def stage_scene(mode="concert_audience", presence="face"):
    scene, _ = setup()
    scene.update(ip="concert", title="演出之夜", play_mode=mode, characters=[],
                 setting="体育场内的舞台与观众区", props="无字应援棒", lighting="场内侧前方暖光",
                 visual={"subject": "photographic", "environment": "photographic"})
    scene["user"] = {"mode": "in_story" if mode == "my_stage" else "traveler",
                     "role": "歌手" if mode == "my_stage" else "观众", "position": "left",
                     "presence": presence, "action": "等待灯光亮起", "outfit": "银灰色外套"}
    if mode == "concert_audience":
        scene["performance"] = {"act": "Queen，1986 Wembley", "visible": True,
                                "description": "远处舞台上黄色短夹克主唱举起话筒杆，吉他、贝斯、鼓组各在其位"}
    return scene


@pytest.mark.parametrize("presence", ["face", "back", "hands"])
@pytest.mark.parametrize("act,description", [
    ("Michael Jackson", "黑礼帽、单只亮片手套与舞步轮廓"),
    ("五月天", "五人乐队各在主唱、双吉他、贝斯与鼓组站位"),
    ("初音未来", "动画歌手的青绿色双马尾与舞台服装"),
])
def test_named_act_survives_without_solo_or_companion_conflicts(presence, act, description):
    scene = stage_scene(presence=presence)
    scene["performance"].update(act=act, description=description)
    if act == "初音未来":
        scene["visual"]["characters"] = "animation_3d"
    request = build(scene=scene)
    prompt = request["prompt"]
    assert act in prompt and description in prompt
    assert "主角是台下观众" in prompt and "远处舞台" in prompt
    assert SOLO_TEXT not in prompt and CAST_HIDDEN_TEXT not in prompt and CHECKIN_TEXT not in prompt
    assert MY_STAGE_TEXT not in prompt and "不安排演出者与主角近距离合影或接触" in prompt
    assert "面部细节不可辨" in prompt and "大屏若入镜，只显示抽象灯光" in prompt
    assert STAGE_LIGHT_TEXT in prompt and FILM_LIGHT_TEXT not in prompt
    assert request["referenced_image_paths"] == ["/in/me.jpg"]
    if presence != "face":
        assert USER_PRESENCE_TEXT[presence] in prompt
        assert "脸清楚受光" not in prompt
    if act == "初音未来":
        assert "舞台表演者若入镜，采用三维动画" in prompt
        assert "不把主角动画化" in prompt


@pytest.mark.parametrize("presence", ["face", "back", "hands"])
def test_my_stage_keeps_the_user_as_singer(presence):
    scene = stage_scene("my_stage", presence)
    prompt = build(scene=scene)["prompt"]
    assert "主角是本场演出的歌手" in prompt
    assert "主角是台下观众" not in prompt and "以来访者身份" not in prompt
    assert "银灰色外套" in prompt and MY_STAGE_TEXT in prompt and SOLO_TEXT not in prompt
    if presence != "face":
        assert USER_PRESENCE_TEXT[presence] in prompt


@pytest.mark.parametrize("role,action", [
    ("电吉他手", "张嘴呐喊，身体随扫弦发力，左手按弦右手拨弦"),
    ("架子鼓手", "坐在鼓凳上，双手各持一根鼓棒，重击后鼓棒弹起"),
    ("贝斯手", "宽站姿随节奏前倾，左手压弦右手拨弦"),
    ("键盘手", "上身前倾，双手分区压下琴键，表情投入"),
])
def test_musician_role_and_explosive_action_are_not_overridden(role, action):
    scene = stage_scene("my_stage")
    scene["user"].update(role=role, action=action)
    prompt = build(scene=scene)["prompt"]
    assert f"主角是本场演出的{role}" in prompt and action in prompt
    assert "主角是本场演出的歌手" not in prompt
    assert STAGE_FACE_TEXT in prompt and FACE_TEXT not in prompt and FACE_LIGHT_TEXT not in prompt
    assert "强烈表情不改变本人脸型与骨相" in prompt
    assert "真实接触与支撑" in prompt


@pytest.mark.parametrize("role,presence,setting,action,props", [
    ("电吉他手", "face", "原创成年贝斯手侧后方近旁入镜，和主角背靠背",
     "左手按电吉他弦、右手扫弦，队友以自己的右手拨贝斯弦回应",
     "主角黑色电吉他、队友红色贝斯，各自肩带承托，琴颈朝向两侧"),
    ("电吉他手", "back", "鼓手在主角后方鼓凳上，以侧后方入镜",
     "停奏间隙转向鼓手点头，右手离开琴弦示意，鼓手持两根鼓棒接重拍",
     "主角电吉他由琴带承托；鼓手双脚踏地，鼓凳和鼓组独立"),
    ("主唱", "face", "原创成年键盘手在侧后方，双方各有演奏空间",
     "主角唱完一句侧身回应，键盘手抬眼并用自己的双手继续触键",
     "主角手持话筒；队友的键盘由支架承重"),
    ("架子鼓手", "back", "停奏后主角离开鼓凳，与原创成年队友在舞台前沿面向观众",
     "主角将鼓棒收在左手，与贝斯手共同鞠躬谢幕",
     "鼓组留在后方；队友贝斯由自己的琴带承托"),
])
def test_planned_band_interaction_survives_without_solo_or_distance_conflicts(role, presence, setting, action, props):
    scene = stage_scene("my_stage", presence)
    scene.update(setting=setting, props=props, framing="mid_interactive")
    scene["user"].update(role=role, action=action)
    request = build(scene=scene)
    prompt = request["prompt"]
    for detail in (f"主角是本场演出的{role}", setting, action, props):
        assert detail in prompt
    assert SOLO_TEXT not in prompt and "其他乐手只作远景伴奏" not in prompt
    assert MY_STAGE_TEXT in prompt
    assert request["referenced_image_paths"] == ["/in/me.jpg"]
    assert scene["characters"] == [] and "performance" not in scene


def test_explicit_solo_is_preserved_when_chaining_after_a_band_shot():
    scene = stage_scene("my_stage")
    scene.update(setting="本镜为单人独奏，队友不入镜", props="仅主角自己的电吉他")
    scene["user"].update(role="电吉他手", action="独自完成尾奏，左手推弦，右手拨弦")
    request = build(scene=scene, chain_ref=Path("/synthetic/band-opening.png"))
    prompt = request["prompt"]
    assert scene["setting"] in prompt and scene["user"]["action"] in prompt
    assert "明确独奏或本镜未安排队友时，不额外添加，也不从首图带入" in prompt
    assert request["referenced_image_paths"] == ["/in/me.jpg", "/synthetic/band-opening.png"]


def test_stage_role_is_required_even_if_card_uses_traveler():
    scene = stage_scene("my_stage")
    scene["user"]["mode"] = "traveler"
    del scene["user"]["role"]
    with pytest.raises(CardError) as exc:
        build(scene=scene)
    assert exc.value.code == "missing_role"


def test_stage_pose_advice_keeps_expression_and_instrument(capsys):
    card = concert_set("my_stage")
    card["shots"][0]["framing"] = "knee_up"
    card["shots"][0]["user"].update(role="电吉他手", action="握着电吉他，仰头露齿大笑，目光看向镜头")
    card["shots"][3]["user"].update(role="电吉他手", action="仰头张嘴，身体发力，目光看向镜头")
    sets.validate_set_card(card)
    warnings = capsys.readouterr().err
    assert "舞台表演：保留已选表情与演奏动作" in warnings
    assert "采用舞台转头或仰俯动作" in warnings
    assert "改闭嘴浅笑、惊喜、专注等" not in warnings
    assert "那张只拿纸、本子" not in warnings
    assert "其余改脸朝镜头" not in warnings
    assert "第 2 张改成在做事" not in warnings
    assert "建议封面用胸口以上的近景" not in warnings


def test_concert_audience_keeps_existing_face_guidance():
    prompt = build(scene=stage_scene("concert_audience"))["prompt"]
    assert FACE_TEXT in prompt and FACE_LIGHT_TEXT in prompt and STAGE_FACE_TEXT not in prompt


def test_absent_performer_does_not_leak_description_or_chain_performer():
    scene = stage_scene()
    scene["setting"] = "体育场外的散场通道"
    scene["performance"]["visible"] = False
    prompt = build(scene=scene, chain_ref=Path("/synthetic/first.png"))["prompt"]
    assert scene["performance"]["description"] not in prompt
    assert "本镜演出者不入镜，不从首图带出演出者" in prompt
    assert "体育场外的散场通道" in prompt and "主角在观众区观演" not in prompt
    assert "大屏若入镜" in prompt and "若有彩色灯束或观众灯海" in prompt


@pytest.mark.parametrize("change,code", [
    (lambda s: s.pop("performance"), "concert_needs_performance"),
    (lambda s: s["performance"].pop("description"), "performance_needs_description"),
    (lambda s: s["performance"].update(visible="yes"), "invalid_scene"),
    (lambda s: s.update(play_mode="my_stage"), "performance_wrong_mode"),
    (lambda s: s.update(play_mode="genre_scene"), "performance_wrong_mode"),
    (lambda s: s.update(characters=setup()[0]["characters"]), "stage_no_companion_cast"),
])
def test_incomplete_or_misrouted_performance_is_rejected(change, code):
    scene = stage_scene()
    change(scene)
    with pytest.raises(CardError) as exc:
        build(scene=scene)
    assert exc.value.code == code


def concert_set(mode, status="user_confirmed"):
    shots = []
    for n, role in enumerate(sets.ROLES):
        scene = stage_scene(mode, ["face", "back", "hands", "face", "back"][n])
        scene.update(id="concert-" + role, status=status,
                     framing=["close_up", "wide", "mid_interactive", "waist_up", "wide"][n],
                     setting=["场馆入口", "看台", "座位前", "安可现场", "散场通道"][n])
        scene["user"]["position"] = "right" if n % 2 else "left"
        if mode == "concert_audience":
            scene["performance"]["visible"] = n in (1, 3)
        shots.append(scene)
    return {"schema_version": "1", "set_id": "hgs1", "status": status, "shots": shots}


def classic_concert_set():
    """Story 2 is the first actual submission; only presentation swaps it with story 1."""
    card = concert_set("concert_audience")
    for scene, title, presence in zip(card["shots"],
                                      ["入场期待", "终于看见TA", "身在现场", "全场高潮", "散场余韵"],
                                      ["face", "back", "hands", "back", "face"]):
        scene["title"] = title
        scene["user"]["presence"] = presence
    card["shots"][4]["framing"] = "waist_up"
    card["shots"] = [card["shots"][i - 1] for i in [2, 1, 3, 4, 5]]
    card["story_order"] = [2, 1, 3, 4, 5]
    return card


@pytest.mark.parametrize("order", [[1, 2, 3, 4], [1, 2, 3, 4, 5, 6], [2, 2, 3, 4, 5],
                                   [0, 2, 3, 4, 5], [1, 2, 3, 4, 6], [True, 2, 3, 4, 5]])
def test_story_order_must_be_a_complete_unambiguous_permutation(order):
    card = classic_concert_set()
    card["story_order"] = order
    with pytest.raises(CardError) as exc:
        sets.require_set_shape(card)
    assert exc.value.code == "invalid_set"


def test_core_first_native_sequence_keeps_execution_and_reference_indices(tmp_path, png_factory):
    ws, photo, _, path = set_workspace(tmp_path, png_factory)
    card = classic_concert_set()
    path.write_text(json.dumps(card))
    base = ["--set-card", path, "--photo", photo, "--workspace", ws]
    image = tmp_path / "core.png"
    image.write_bytes(png_factory())
    for index, story_index in enumerate([2, 1, 3, 4, 5], 1):
        code, out = cli("compile-shot", "--index", index, *base)
        assert code == 0 and out["story_index"] == story_index, out
        request = json.loads(Path(out["request_path"]).read_text())
        assert request["set"]["index"] == index
        assert request["card_ref"]["scene_id"] == "concert/" + card["shots"][index - 1]["id"]
        if index in (1, 4):
            assert "本镜远处舞台表演" in request["prompt"]
        else:
            assert "本镜演出者不入镜" in request["prompt"]
        if index > 1:
            assert Path(request["referenced_image_paths"][-1]).read_bytes() == image.read_bytes()
        assert cli("set-record", "--set-card", path, "--workspace", ws, "--index", index,
                   "--status", "generated", "--image", image)[0] == 0
    ledger_path = ws / "outputs/sets/hgs1/set.json"
    before = ledger_path.read_bytes()
    code, status = cli("set-status", "--set-card", path, "--workspace", ws)
    assert code == 0 and status["story_order"] == [2, 1, 3, 4, 5]
    assert [item["index"] for item in status["items"]] == [1, 2, 3, 4, 5]
    assert ledger_path.read_bytes() == before
    assert "story_order" not in json.loads(before)  # presentation never rewrites the ledger


@pytest.mark.parametrize("mode,status,states,count", [
    ("ok", "set_generated", ["generated"] * 5, 5),
    ("refuse", "set_partial", ["rejected"] + ["cancelled"] * 4, 1),
    ("crash_after_0", "set_paused_unknown", ["claimed"] + ["pending"] * 4, 1),
])
def test_core_first_fake_backend_preserves_stop_and_claim_rules(tmp_path, png_factory, mode, status, states, count):
    ws, photo, _, path = set_workspace(tmp_path, png_factory)
    card = classic_concert_set()
    path.write_text(json.dumps(card))
    code, result = cli("generate-set", "--set-card", path, "--photo", photo, "--workspace", ws,
                       "--authorized-count", 5, "--codex", FAKE, env=fake_env(tmp_path, mode))
    assert code == (0 if mode == "ok" else 2), result
    assert result["status"] == status and result["quota_used"] == count
    assert [item["story_index"] for item in result["results"]] == [2, 1, 3, 4, 5]
    ledger = sets.load_ledger(ws, card)
    assert [item["status"] for item in ledger["items"]] == states
    requests = list((ws / "outputs").glob("*/request.json"))
    assert len(requests) == count
    first = json.loads(Path(result["results"][0]["request_path"]).read_text())
    assert first["card_ref"]["scene_id"] == "concert/" + card["shots"][0]["id"]
    assert "本镜远处舞台表演" in first["prompt"]
    assert "cover_likeness" not in ledger  # the core is a back shot, not evidence of face likeness


def test_audience_replacement_removes_performer_but_preserves_climax():
    scene = classic_concert_set()["shots"][3]
    original = scene["performance"].pop("description")
    scene["performance"]["visible"] = False
    scene["framing"] = "close_up"
    scene["user"].update(presence="face", action="面对前方舞台投入跟唱，嘴张开，镜头从舞台方向拍观众的反应")
    prompt = build(scene=scene, chain_ref=Path("/synthetic/core.png"))["prompt"]
    assert original not in prompt and "本镜远处舞台表演" not in prompt
    assert "本镜演出者不入镜，不从首图带出演出者" in prompt
    assert scene["user"]["action"] in prompt
    assert scene["user"]["outfit"] in prompt and "本人" in prompt


@pytest.mark.parametrize("mode", ["my_stage", "concert_audience"])
def test_five_shot_native_path_retains_claim_and_chain_semantics(tmp_path, png_factory, mode):
    ws, photo, _, path = set_workspace(tmp_path, png_factory)
    path.write_text(json.dumps(concert_set(mode)))
    base = ["--set-card", path, "--photo", photo, "--workspace", ws]
    image = tmp_path / "synthetic.png"
    image.write_bytes(png_factory())
    for index in range(1, 6):
        code, result = cli("compile-shot", "--index", index, *base)
        assert code == 0, result
        req = json.loads(Path(result["request_path"]).read_text())
        assert req["set"]["index"] == index
        assert len(req["referenced_image_paths"]) == (1 if index == 1 else 2)
        code, duplicate = cli("compile-shot", "--index", index, *base)
        assert code == 2 and duplicate["status"] == "shot_already_claimed"
        assert cli("set-record", "--set-card", path, "--workspace", ws, "--index", index,
                   "--status", "generated", "--image", image)[0] == 0
    _, ledger = cli("set-status", "--set-card", path, "--workspace", ws)
    assert [item["status"] for item in ledger["items"]] == ["generated"] * 5


@pytest.mark.parametrize("mode", ["my_stage", "concert_audience"])
def test_new_route_first_failure_still_cancels_remaining_shots(tmp_path, png_factory, mode):
    ws, photo, _, path = set_workspace(tmp_path, png_factory)
    path.write_text(json.dumps(concert_set(mode)))
    assert cli("compile-shot", "--index", 1, "--set-card", path, "--photo", photo, "--workspace", ws)[0] == 0
    assert cli("set-record", "--set-card", path, "--workspace", ws, "--index", 1, "--status", "failed")[0] == 0
    _, ledger = cli("set-status", "--set-card", path, "--workspace", ws)
    assert [item["status"] for item in ledger["items"]] == ["failed"] + ["cancelled"] * 4


def test_concert_draft_is_checked_without_confirmation_or_side_effects(tmp_path):
    card = concert_set("concert_audience", "unverified")
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(card))
    before = path.read_bytes()
    code, result = cli("check-pose-variety", "--set-card", path, env={"PATH": ""})
    assert code == 0 and result["advisory_only"] is True
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
    del card["shots"][4]["performance"]
    path.write_text(json.dumps(card))
    code, result = cli("check-pose-variety", "--set-card", path)
    assert code == 2 and result["status"] == "concert_needs_performance"
    confirmed = copy.deepcopy(card)
    confirmed["status"] = "user_confirmed"
    for scene in confirmed["shots"]:
        scene["status"] = "user_confirmed"
        require_valid(scene, "scene")
    with pytest.raises(CardError, match="concert_needs_performance"):
        sets.validate_set_card(confirmed)
