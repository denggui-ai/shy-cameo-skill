"""Five-image sets: set card validation and the per-set ledger.

A set card holds five complete scene cards (cover, wide, interaction, shy, ending). The ledger
lives in WS/outputs/sets/<set_id>/set.json; image 1 is copied byte-exact to chain.png and
becomes the consistency reference for the later images.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from .cards import CardError, require_valid
from .compiler import check_cover_level, check_retired_presence, check_user_presence
from .library import sha256_file

ROLES = ("cover", "wide", "interaction", "shy", "ending")
SET_SIZE = len(ROLES)
SHY_INDEX = ROLES.index("shy") + 1  # legacy slot label; no fixed presence requirement
# Avoid five near-identical camera-facing waist shots.
MIN_FRAMINGS = 3
MIN_POSITIONS = 2
MAX_CAMERA_GAZE = 2
# D25: one or two clear face shots per set (cover + emotional peak); the rest are back,
# hands, over-shoulder, silhouette or wide, recognised by consistent hair, outfit and build.
MAX_FACE_SHOTS = 2
BODY_PRESENCE = ("back",)  # cropped only hides the head; it is not a mid-ground back shot
# Head-down, profile and look-back poses drift furthest from the user's face (2026-10-22 review);
# the face should stay open to the lens even when the eyes look elsewhere. D20: no turns on face
# shots; one tilted-head mood shot per set is allowed (Owner 2026-10-23, e.g. the Wukong crown shot).
MAX_HEAD_TURN = 0
MAX_HEAD_TILT = 1
HEAD_TURN_POSE = re.compile(r"侧脸|背身|背对镜头|背朝镜头|回头|扭头|转过头|歪头|偏头")
HEAD_TILT_POSE = re.compile(r"低头|垂头|埋头|俯首|仰头")
# D31: a V-sign or other lens-posing hand gesture reads as a selfie, not a film still, and puts a hand by the face.
POSE_GESTURE = re.compile(r"比\s*[Vv]|剪刀手|比耶|比心|比个?心|竖大拇指|摆\s*pose")
# Gaze beside or past the camera does not count as looking into the lens.
LENS_TARGET = r"镜头(?![外后左右旁侧前]|[上下][方侧面])"
CAMERA_GAZE = re.compile(r"(看|望|盯|瞥|直视|凝视|注视|面向|面对|正对|对|朝|冲|直面|目视)(向|着|了一眼)?" + LENS_TARGET)
EYES_AT_CAMERA = re.compile(r"(落在|停在|投向|移向|转向)\s*" + LENS_TARGET)
FACING_VERBS = {"面向", "面对", "正对", "对", "朝", "冲", "直面"}
EYE_TARGET_CLAUSE = re.compile(r"(?:目光|视线|眼神|眼睛|双眼|低头|垂眼|垂眸)([^，,。；;！!？?\n]*)")
DIRECTED_EYES = re.compile(r"(?:看(?:向|着)?|望向|盯(?:向|着)?|凝视|注视|落[在向]|停在|投向|移向|转向|朝|沿|跟随|追随)\s*\S")
# "背对/背朝/背冲镜头" faces away; "弓背看向镜头" still looks.
FACING_AWAY_VERBS = ("对", "朝", "冲")
# A negation up to 4 characters before the verb, within the same clause ("没有回头看镜头",
# "不要看向镜头"). A bare 不 counts only right before the verb: "不时", "毫不犹豫" are not negations;
# 别 inside "特别/告别/区别" is not one either.
GAZE_NEGATION = re.compile(r"不[要再会去敢想肯用必曾]|不$|没|未|(?<![特告区分个性类识辨级离派])别|勿")
CLAUSE_BREAK = re.compile(r"[，,。；;、！!？?\s]")
NEGATION_WINDOW = 4
# D33: two face shots in one set must change at least two of framing, camera angle and sit/stand.
MIN_FACE_DIFFERENCES = 2
SEATED_POSE = re.compile(r"坐[在着下]|蹲|跪|靠坐")
# A broad laugh or an object in hand on a face shot drifted the face and broke fingers (2026-10-26 Wukong r1/r2 shot 4).
BIG_LAUGH = re.compile(r"大笑|开怀|露齿|咧嘴|哈哈")
HOLDING = re.compile(r"捧|握|端着|拿着|攥")
HEADWEAR = re.compile(r"冠|盔|头饰|头面|簪|帽|头巾")
LONG_WEAPON_GRIP = re.compile(r"(握|扶|拄|抓).{0,6}(棒|棍|枪|剑|刀|杖)")
# "不露齿大笑": a negation word close before the hit, within the clause; 忍不住、毫不、不时、不禁、情不自禁 and
# 告别/特别 are not negations of the action that follows.
PLAIN_NEGATION = re.compile(r"(?<![忍毫])不(?![住时禁自])|没|未|(?<![特告区分个性类识辨级离派])别|勿")


def _negated(text: str, start: int) -> bool:
    lo = max(0, start - NEGATION_WINDOW)
    breaks = [b.end() for b in CLAUSE_BREAK.finditer(text, lo, start)]
    lo = breaks[-1] if breaks else lo
    # Search in place so the 别 lookbehind sees characters left of the window.
    return bool(GAZE_NEGATION.search(text, lo, start))


def _camera_target(text: str, match) -> bool:
    return not (_negated(text, match.start()) or (
        match.start() > 0 and text[match.start() - 1] == "背" and match.group(1) in FACING_AWAY_VERBS))


def _explicit_eye_targets(action: str) -> tuple[bool, bool]:
    at_camera = away = False
    for clause in EYE_TARGET_CLAUSE.findall(action):
        camera_targets = list(CAMERA_GAZE.finditer(clause)) + list(EYES_AT_CAMERA.finditer(clause))
        if camera_targets:
            looks_at_camera = any(_camera_target(clause, m) for m in camera_targets)
            at_camera |= looks_at_camera
            away |= not looks_at_camera
        elif any(not _negated(clause, m.start()) for m in DIRECTED_EYES.finditer(clause)):
            away = True
    return at_camera, away


def camera_gaze(action: str) -> bool:
    eyes_at_camera, eyes_away = _explicit_eye_targets(action)
    if eyes_at_camera:
        return True
    for m in CAMERA_GAZE.finditer(action):
        if not _camera_target(action, m):
            continue
        # A clear eye target takes precedence over a camera-facing body or face.
        # Direct lens-gaze verbs (or a wink at the lens) still count.
        if eyes_away and m.group(1) in FACING_VERBS and not action[m.end():].startswith("眨眼"):
            continue
        return True
    return False


def _pose_hit(pattern: re.Pattern, action: str) -> bool:
    return any(not _negated(action, m.start()) for m in pattern.finditer(action))


def head_turn_pose(action: str) -> bool:
    return _pose_hit(HEAD_TURN_POSE, action)


def head_tilt_pose(action: str) -> bool:
    return _pose_hit(HEAD_TILT_POSE, action)


def face_away_pose(action: str) -> bool:
    return head_turn_pose(action) or head_tilt_pose(action)


def _plain_hit(pattern: re.Pattern, action: str) -> bool:
    for m in pattern.finditer(action):
        lo = max(0, m.start() - NEGATION_WINDOW)
        breaks = [b.end() for b in CLAUSE_BREAK.finditer(action, lo, m.start())]
        if not PLAIN_NEGATION.search(action, breaks[-1] if breaks else lo, m.start()):
            return True
    return False


def _face_dims(shot: dict) -> tuple:
    return (shot["framing"], shot.get("camera_angle", "eye"), _plain_hit(SEATED_POSE, shot["user"]["action"]))


def check_face_shot_guards(shots: list) -> None:
    """D33 variety between face shots, plus laugh, hands and long-weapon hints (2026-10-26 spec)."""
    faces = [(n, s) for n, s in enumerate(shots, 1) if s["user"].get("presence", "face") == "face"]
    for i, (a, sa) in enumerate(faces):
        for b, sb in faces[i + 1:]:
            changed = sum(x != y for x, y in zip(_face_dims(sa), _face_dims(sb)))
            if changed < MIN_FACE_DIFFERENCES:
                print(f"第 {a} 和第 {b} 张露脸，景别/机位/坐站只换了 {changed} 样；D33 要求至少换两样（表情也要跟事件变）；"
                      "仅建议，不阻断", file=sys.stderr)
    for n, s in faces:
        action = s["user"]["action"]
        if _plain_hit(BIG_LAUGH, action):
            print(f"第 {n} 张露脸写了大笑/露齿，笑容最容易让脸不像本人；改闭嘴浅笑、惊喜、专注等，大笑放背影或远景；"
                  "仅建议，不阻断", file=sys.stderr)
        if _plain_hit(HOLDING, action):
            print(f"第 {n} 张露脸手里拿着东西，手指最易出错又抢脸；碗、杯、兵器放只拍手的特写；"
                  "“在做事”那张只拿纸、本子这类轻东西，举在胸前、下巴以下不挡脸，不放膝上桌上；仅建议，不阻断", file=sys.stderr)
    # Two face shots that both look at the camera read as one mould (lessons 29/34/35); Abao r5-3 fix: eyes on hands.
    gazing = [n for n, s in faces if camera_gaze(s["user"]["action"])]
    # D32 tail: opera, headwear or a changed hairstyle/make-up keeps both face shots on the lens.
    changed_look = any(s.get("play_mode") == "opera_costume" or s["user"].get("hairstyle") or s["user"].get("makeup")
                       or _plain_hit(HEADWEAR, f'{s["user"].get("outfit", "")}，{s["user"].get("costume", "")}')
                       for _, s in faces)
    if len(faces) >= 2 and len(gazing) == len(faces) and not changed_look:
        print(f"第 {'、'.join(map(str, gazing))} 张露脸都看镜头，并排容易像同一个模子；第 2 张改成在做事："
              "脸朝镜头，手里的轻东西举在胸前，眼睛看着它、不低头，表情专注不笑；仅建议，不阻断", file=sys.stderr)
    for n, s in enumerate(shots, 1):
        if _plain_hit(LONG_WEAPON_GRIP, s["user"]["action"]):
            print(f"第 {n} 张主角握着长兵器，长棒长枪最容易画错手和兵器；改成兵器立在一旁或交给陪同角色；仅建议，不阻断",
                  file=sys.stderr)


def check_episode_match(shots: list, characters: dict) -> None:
    """A costume variant with `episodes` should match the set's story (2026-10-26 spec C)."""
    context = shots[0].get("film_context") or ""
    for c in {(c["character_id"], c["variant_id"]) for s in shots for c in s.get("characters") or []}:
        card = characters.get(c[0]) or {}
        variant = next((v for v in card.get("variants", []) if v.get("variant_id") == c[1]), {})
        keys = [re.split(r"[（(]", e, 1)[0].strip() for e in variant.get("episodes", [])]
        if keys and not any(k and k in context for k in keys):
            print(f"{c[0]} 这身造型（{c[1]}）对应的情节是「{'」「'.join(keys)}」，本套 film_context 没写到其中任何一段，"
                  "造型和情节对不上；改造型或改情节；仅建议，不阻断", file=sys.stderr)
LEDGER_NAME = "set.json"
CHAIN_NAME = "chain.png"
RESULTS = ("generated", "rejected", "failed")


def require_set_shape(card: dict) -> None:
    """Schema check with a migration hint for cards written for the old four-shot set."""
    shots = card.get("shots")
    if isinstance(shots, list) and len(shots) == 4:
        raise CardError("set_size_changed", "一套已改为 5 张：请按当前创意补齐五张并确认")
    require_valid(card, "set")


def validate_set_card(card: dict) -> None:
    require_set_shape(card)
    if card["status"] != "user_confirmed":
        raise CardError("set_not_confirmed", f"这套照片的 {SET_SIZE} 张分镜还没有经用户确认")
    first = card["shots"][0]
    for n, shot in enumerate(card["shots"], 1):
        check_retired_presence(shot)
        require_valid(shot, "scene")
        check_cover_level(shot)
        check_user_presence(shot)
        if shot["status"] != "user_confirmed":
            raise CardError("scene_not_confirmed", f"第 {n} 张分镜尚未经用户确认")
        for key in ("ip", "play_mode", "style", "aspect"):
            if shot[key] != first[key]:
                raise CardError("set_inconsistent", f"第 {n} 张的 {key} 与第 1 张不一致")
    check_pose_variety(card["shots"])
    check_face_shot_guards(card["shots"])
    if len({s['setting'].strip() for s in card['shots']}) == 1:
        print("提示：五张同景；按已确认创意检查动作与叙事差异，不因此阻断。", file=sys.stderr)


def check_pose_variety(shots: list) -> None:
    framings = {s["framing"] for s in shots}
    if len(framings) < MIN_FRAMINGS:
        print(f"5 张至少用 {MIN_FRAMINGS} 种景别（close_up、waist_up、knee_up、mid_interactive），现在只有 {len(framings)} 种；仅建议，不阻断", file=sys.stderr)
    positions = {s["user"]["position"] for s in shots}
    if len(positions) < MIN_POSITIONS:
        print(f"5 张的主角站位至少 {MIN_POSITIONS} 种，现在都在同一侧；仅建议，不阻断", file=sys.stderr)
    gaze = [n for n, s in enumerate(shots, 1) if camera_gaze(s["user"]["action"])]
    if len(gaze) > MAX_CAMERA_GAZE:
        print(f"最多 {MAX_CAMERA_GAZE} 张写看向镜头（放在露脸的封面和情绪最高点），现在第 {'、'.join(map(str, gaze))} 张都是；"
              "可考虑其他视线；仅建议，不阻断", file=sys.stderr)
    # Back or hands-only shots hide the face by design; they are not drift risks.
    shown = [(n, s["user"]["action"]) for n, s in enumerate(shots, 1) if s["user"].get("presence", "face") == "face"]
    turns = [n for n, action in shown if head_turn_pose(action)]
    if len(turns) > MAX_HEAD_TURN:
        print(f"第 {'、'.join(map(str, turns))} 张主角露脸时侧脸、回头或歪头；这类姿势最容易不像本人，"
              "建议改成脸朝镜头、眼睛看镜头或身前手里的道具，或改背影/只拍手；仅建议，不阻断", file=sys.stderr)
    tilts = [n for n, action in shown if head_tilt_pose(action)]
    if len(tilts) > MAX_HEAD_TILT:
        print(f"第 {'、'.join(map(str, tilts))} 张主角露脸时低头或仰头，超过 {MAX_HEAD_TILT} 张；"
              "只留最有戏的一张，其余改脸朝镜头或改背影/只拍手；仅建议，不阻断", file=sys.stderr)
    faces = [n for n, _ in shown]
    if len(faces) > MAX_FACE_SHOTS:
        print(f"第 {'、'.join(map(str, faces))} 张都露脸，超过 {MAX_FACE_SHOTS} 张；只留封面和情绪最高点 1–2 张清楚正脸，"
              "其余改背影、只拍手、越肩、剪影或远景，靠整组一致的发色、衣服、首饰认人；仅建议，不阻断", file=sys.stderr)
    elif not faces:
        print(f"{len(shots)} 张都不露脸；建议第 1 张封面和情绪最高点各露一张清楚正脸；仅建议，不阻断", file=sys.stderr)
    elif faces[0] != 1:
        print("第 1 张（封面）不露脸；封面宜用清楚正脸，后几张以它为一致性参照；仅建议，不阻断", file=sys.stderr)
    # Full-body and wide face shots scored lowest likeness in the 2026-10-22 stress run.
    wide = [n for n in faces if shots[n - 1]["framing"] in ("full_body", "wide")]
    if wide:
        print(f"第 {'、'.join(map(str, wide))} 张露脸却用全身或远景，这类景别最不像本人；建议改到膝/到腰，或改背影；仅建议，不阻断",
              file=sys.stderr)
    # D34: the cover face is the likeness anchor; waist-up covers drifted, close-ups held (2026-10-25 A/B).
    if faces and faces[0] == 1 and shots[0]["framing"] != "close_up":
        print("第 1 张（封面）露脸但不是近景（close_up）；封面脸小最容易不像本人，也会带偏后几张；"
              "建议封面用胸口以上的近景，角色仍放身后深处；仅建议，不阻断", file=sys.stderr)
    # D26: a set of paws alone reads as a generic hand; one mid-ground body shot carries the identity.
    cast = [c for s in shots for c in s.get("characters") or []]
    if cast and not any(c["character_presence"] in BODY_PRESENCE for c in cast):
        print("陪同角色整套只露手、尾巴等局部，看不出是谁；建议至少 1 张让角色以中景背影出场"
              "（和主角差不多远、不比主角近，用门框、窗格等实体挡住一部分）；仅建议，不阻断", file=sys.stderr)
    if _pose_hit(POSE_GESTURE, shots[0]["user"]["action"]):
        print("第 1 张（封面）写了比 V、比心这类对镜头摆拍手势；像自拍不像电影剧照，手也靠近脸；"
              "建议换成本章故事里的动作（如试装抻衣摆、扶门），手远离脸；仅建议，不阻断", file=sys.stderr)
    # D29: a cover with only a paw or shadow is unrecognisable without a hint (2026-10-24 blind test).
    cover_cast = shots[0].get("characters") or []
    if cover_cast and not any(c["character_presence"] in BODY_PRESENCE for c in cover_cast):
        print("第 1 张（封面）陪同角色只露手、爪、影子等局部，不说认不出是谁；建议封面放角色中景背影，"
              "站在主角身后深处、比她明显远且小，用实体挡住一部分；仅建议，不阻断", file=sys.stderr)


def set_dir(ws: Path, set_id: str) -> Path:
    return Path(ws) / "outputs" / "sets" / set_id


def load_ledger(ws: Path, card: dict) -> dict:
    # The directory always comes from the card; the file's own set_id is never trusted.
    path = set_dir(ws, card["set_id"]) / LEDGER_NAME
    if path.is_file():
        ledger = json.loads(path.read_text(encoding="utf-8"))
        if ledger.get("set_id") != card["set_id"] or len(ledger.get("items") or []) != SET_SIZE:
            raise CardError("ledger_mismatch", "套图账本里的编号或张数与套图卡不一致，请重新开始这套照片")
        return ledger
    traces = submission_traces(ws, card["set_id"])
    if traces:
        # A lost ledger is an unknown history, never a fresh set: restarting could pay twice.
        raise CardError("ledger_missing", f"套图账本缺失，但已有 {len(traces)} 处提交痕迹（如 {traces[0]}）；"
                        "结果未知，请先核对历史，不会按未开始重新编译或提交")
    return {"set_id": card["set_id"], "chain_image": None, "chain_sha256": None,
            "items": [{"index": i, "role": r, "run_id": None, "status": "pending"}
                      for i, r in enumerate(ROLES, 1)]}


def submission_traces(ws: Path, set_id: str) -> list:
    """Evidence that this set was already compiled or generated: a registered chain image file
    or a request tagged with the set. An empty pre-created directory is not a trace."""
    traces = []
    chain = set_dir(ws, set_id) / CHAIN_NAME
    if chain.is_file():
        traces.append(str(chain))
    for request in sorted((Path(ws) / "outputs").glob("*/request.json")):
        try:
            data = json.loads(request.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("set"), dict) and data["set"].get("set_id") == set_id:
            traces.append(str(request.parent))
    return traces


def save_ledger(ws: Path, card: dict, ledger: dict) -> Path:
    if ledger.get("set_id") != card["set_id"]:
        raise CardError("ledger_mismatch", "套图账本里的编号与套图卡不一致，请重新开始这套照片")
    path = set_dir(ws, card["set_id"]) / LEDGER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def chain_ref(ws: Path, card: dict, ledger: dict) -> Path:
    """Return the registered chain image only if path and bytes still match the registration."""
    err = CardError("chain_tampered", "套图第 1 张的登记记录被改动或文件不一致，请重新开始这套照片")
    expected = (set_dir(ws, card["set_id"]) / CHAIN_NAME).resolve()
    recorded = ledger.get("chain_image")
    if not recorded or not ledger.get("chain_sha256"):
        raise err
    if Path(recorded).resolve() != expected or not expected.is_file():
        raise err
    if sha256_file(expected) != ledger["chain_sha256"]:
        raise err
    return expected


def item(ledger: dict, index: int) -> dict:
    if not 1 <= index <= SET_SIZE:
        raise CardError("bad_index", f"套图只有第 1 到 {SET_SIZE} 张：{index}")
    return ledger["items"][index - 1]


def require_claimable(ledger: dict, index: int) -> None:
    it = item(ledger, index)
    if it["status"] == "cancelled":
        raise CardError("set_cancelled", "第 1 张没有成功，这套其余几张已取消、不计额度")
    if it["status"] != "pending":
        raise CardError("shot_already_claimed", f"第 {index} 张已经提交过；单张重拍须重新授权")
    if index > 1 and ledger["chain_image"] is None:
        raise CardError("chain_not_ready", "第 1 张成片还没有登记，不能生成后面几张")


def check_mood_ref(ledger: dict, mood_sha: Optional[str]) -> None:
    """Shots after the first (and reshoots) must use shot 1's mood image bytes, or none if it had none."""
    if ledger.get("mood_ref_sha256") != mood_sha:
        raise CardError("mood_ref_changed", "这套第 1 张用的氛围图和现在不一样，不能混拍")


def check_pet_ref(ledger: dict, pet_sha: Optional[str]) -> None:
    """Like check_mood_ref: every shot of a set uses shot 1's pet photo bytes, or none."""
    if ledger.get("pet_ref_sha256") != pet_sha:
        raise CardError("pet_ref_changed", "这套第 1 张用的宠物照和现在不一样，不能混拍")


def claim(ledger: dict, index: int, run_id: str) -> None:
    require_claimable(ledger, index)
    item(ledger, index).update(status="claimed", run_id=run_id)


def _register_chain(ws: Path, set_id: str, image: Path) -> Path:
    dest = set_dir(ws, set_id) / CHAIN_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image, dest)  # byte copy keeps the C2PA manifest
    if sha256_file(dest) != sha256_file(image):
        dest.unlink()
        raise CardError("copy_mismatch", "套图第 1 张复制后哈希不一致")
    return dest.resolve()


def record(ws: Path, ledger: dict, index: int, status: str, image: Optional[str] = None) -> None:
    it = item(ledger, index)
    if it["status"] != "claimed":
        raise CardError("shot_not_claimed", f"第 {index} 张还没有提交，不能登记结果")
    if status not in RESULTS:
        raise CardError("bad_status", f"结果只能是 {'/'.join(RESULTS)}：{status}")
    if index == 1 and status == "generated":
        if not image:
            raise CardError("missing_image", "第 1 张成功时必须登记成片路径")
        if not Path(image).is_file():
            raise CardError("missing_image", f"找不到第 1 张成片：{image}")
        chain = _register_chain(ws, ledger["set_id"], Path(image))
        ledger["chain_image"] = str(chain)
        ledger["chain_sha256"] = sha256_file(chain)
    it["status"] = status
    if index == 1 and status != "generated":
        for other in ledger["items"][1:]:
            if other["status"] == "pending":
                other["status"] = "cancelled"
