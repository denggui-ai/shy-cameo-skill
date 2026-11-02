"""Compile a confirmed scene card + character cards + user photos into request.json."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .cards import CardError, find_variant, require_valid
from .names import NameEntry, scan

MAX_REFS = 5
MAX_USER_PHOTOS = 2

STYLE_TEXT = {
    "realistic": "电影剧照质感，像{context}，竖幅 {aspect}，真实场景，光线与所选情节、空间相容。",
    "anime": ("日本电视动画的画面质感：干净线条、赛璐璐平涂上色、柔和的手绘背景美术，"
              "角色造型按本套已确认描述呈现，竖幅 {aspect}。"),
}
# D18: the old "check-in photo, imperfection allowed" wording read as phone snapshots (batch 1 set 1).
CHECKIN_STYLE_TEXT = ("有摄影设计的旅行写真，在真实地点拍摄，竖幅 {aspect}，真实色彩但有电影调色；"
                      "光线来自场景并有摄影设计，主角优先、背景有取舍，构图讲究。")
CLASSIC_PORTRAIT_TEXT = ("有电影氛围的主题写真，主题语境为{context}，竖幅 {aspect}。"
                         "人脸与材质真实，光线来自场景并有摄影设计；主角优先、背景有取舍。"
                         "衣装保留角色标志，不过分夸张破损、灰尘与粗粝纹理。")
# Explicit visual choices take precedence over the legacy whole-image style.
VISUAL_TEXT = {"photographic": "真人摄影质感", "animation_2d": "二维动画线条与绘制质感", "animation_3d": "三维动画造型与渲染质感"}
# D17: the visual branch carried no photography direction; works for live-action and animated frames alike.
VISUAL_CRAFT_TEXT = "画面像电影剧照：光线来自场景并有摄影设计，主角优先、背景有取舍。"
# Owner 2026-10-26: every image must look like a film frame, not a phone snapshot; independent of the low-key D30 light.
CINEMA_TEXT = "电影级画质：像电影里的一帧，光有方向、明暗与纵深分明，不是手机随手拍。"
CINEMA_ANIM_TEXT = "电影级画质：像动画电影里的一帧，光有方向、明暗与纵深分明。"
# D30 (photographic environments in the visual branch, not check-in travel shots): "film still" alone drifted into bright ad/travel looks (2026-10-24 Po chapter 1 r17t); spell out low-key motivated light.
BRIGHT_DAY = "明亮日景"
FILM_LIGHT_TEXT = ("电影布光：光有明确方向与光比，画面整体偏暗、暗部保持深色不提亮，背景比主角暗一到两档但结构可辨；"
                   "主光来自场景里的实景光源，环境色与主角肤色分开；中等景深，前景可有一件略虚的实物制造层次；"
                   "主角不必居中，视线方向留白；不用满屏日光把人和背景照得一样亮。")
# Owner 2026-10-28: check-ins read as phone snapshots; travel keeps daylight bright but still lights like a film.
# Night r1 (10-28): four competing sources and a flash-like face read as "messy light, no depth".
CHECKIN_FILM_LIGHT_TEXT = ("旅行电影布光：只认一个主光源，来自场景里的实景光源，其余光源少而暗、放远处虚成光斑；主角比背景亮半档到一档，发丝和肩上有轮廓光；"
                           "亮处偏暖、暗处偏冷；白天户外不把整张压暗，黄昏、夜景、室内才整体偏暗，暗部占画面一半以上；"
                           "中长焦浅景深，主角偏一侧、视线方向留白；不用满屏平光把人和背景照得一样亮。")
# Owner 2026-10-28: a small thing in your day with your own pet; only the user and the pet are in frame.
PET_DAILY_STYLE_TEXT = ("有摄影设计的生活写真，在主角自己的家或日常去处拍摄，竖幅 {aspect}，真实色彩但有电影调色；"
                        "光线来自场景并有摄影设计，主角和宠物优先、背景有取舍，构图讲究。")
DAILY_FILM_LIGHT_TEXT = ("生活电影布光：只认一个主光源，来自场景里的实景光源（窗光、台灯、夜灯、炉火这类），其余光源少而暗、虚成光斑；"
                         "主角比背景亮半档到一档，发丝和肩上有轮廓光；亮处偏暖、暗处偏冷；白天靠窗不把整张压暗，"
                         "傍晚、夜里、拉着窗帘的屋里才整体偏暗，暗部占画面一半以上；中长焦浅景深，主角偏一侧、视线方向留白；"
                         "不用满屏平光把人和背景照得一样亮。")
SOLO_LIFE_MODES = ("location_checkin", "pet_daily")
# 2026-10-28: "light the whole face evenly" gave phone flat light; lessons 34: half the face in shadow drifts the likeness.
FACE_LIGHT_TEXT = ("脸部光：脸上的光来自画面里那个主光源、方向与它一致，不像闪光灯；它从镜头前方偏一侧约 30–45° 给脸柔和的方向感，脸整体受光、额头鼻梁双颊清楚，"
                   "只在脸颊外侧和下颌线轻微渐暗，脸上不切明暗分界；两眼有眼神光；明暗反差放在背景、发丝和肩部轮廓光上。")


def film_light(scene: dict) -> bool:
    # A card that asks for a bright day scene (user or work choice) keeps its own light.
    visual = scene.get("visual") or {}
    return (visual.get("environment") == "photographic" and scene["play_mode"] not in SOLO_LIFE_MODES
            and BRIGHT_DAY not in scene.get("lighting", ""))


def checkin_film_light(scene: dict) -> bool:
    visual = scene.get("visual")
    real = (visual.get("environment") == "photographic") if visual else scene["style"] == "realistic"
    return scene["play_mode"] in SOLO_LIFE_MODES and real and BRIGHT_DAY not in scene.get("lighting", "")


def face_light(scene: dict) -> str:
    # Rides only with a film-light sentence; the portrait branch keeps its length budget (D30).
    face = ((scene.get("user") or {}).get("presence", "face")) == "face"
    lit = film_light(scene) or scene["play_mode"] in SOLO_LIFE_MODES
    return FACE_LIGHT_TEXT if face and lit and subject_style(scene) == "photographic" else ""


def subject_style(scene: dict) -> str:
    return (scene.get("visual") or {}).get("subject", "animation_2d" if scene["style"] == "anime" else "photographic")


# Default film context per play mode; a scene card may override it with film_context (POC run 27 head line).
FILM_CONTEXT = {
    "classic_presence": "经典故事世界中的一次相遇",
    "original_text": "一部忠于原著描写的改编电影",
    "archetype": "一部原创电影",
    "genre_scene": "一部类型电影",
    "opera_costume": "一场传统戏曲演出的后台花絮",
    "pet_daily": "和自家宠物在一起的一件日常小事",
}


def cinema_text(scene: dict) -> str:
    return CINEMA_TEXT if subject_style(scene) == "photographic" else CINEMA_ANIM_TEXT


def style_text(scene: dict) -> str:
    light = DAILY_FILM_LIGHT_TEXT if scene["play_mode"] == "pet_daily" else CHECKIN_FILM_LIGHT_TEXT
    return (_base_style_text(scene) + (light if checkin_film_light(scene) else "")
            + face_light(scene) + cinema_text(scene))


def _base_style_text(scene: dict) -> str:
    visual = scene.get("visual")
    if visual:
        subject = VISUAL_TEXT[visual["subject"]]
        environment = VISUAL_TEXT[visual["environment"]]
        cast = VISUAL_TEXT[visual.get("characters", visual["environment"])]
        identity = "主角保留本人真实面貌，不把主角动画化。" if visual["subject"] == "photographic" else "主角按所选动画表现重绘，保留本人可辨认的特征。"
        return (f"竖幅 {scene['aspect']}；主角采用{subject}；环境采用{environment}；陪同角色若在场，采用{cast}。"
                f"{identity}人物与环境按此分别呈现，接触位置、透视、光线方向协调；"
                f"场景语境：{scene.get('film_context') or FILM_CONTEXT.get(scene['play_mode'], '旅行写真')}。"
                + VISUAL_CRAFT_TEXT + (FILM_LIGHT_TEXT if film_light(scene) else ""))
    if scene["play_mode"] == "location_checkin" and scene["style"] == "realistic":
        return CHECKIN_STYLE_TEXT.format(aspect=scene["aspect"])
    if scene["play_mode"] == "pet_daily" and scene["style"] == "realistic":
        return PET_DAILY_STYLE_TEXT.format(aspect=scene["aspect"])
    context = scene.get("film_context") or FILM_CONTEXT.get(scene["play_mode"], "一次旅行打卡")
    if scene['play_mode'] == 'classic_presence' and scene['style'] == 'realistic':
        return CLASSIC_PORTRAIT_TEXT.format(aspect=scene['aspect'], context=context)
    return STYLE_TEXT[scene["style"]].format(aspect=scene["aspect"], context=context) + (f"场景语境：{context}。" if scene["style"] == "anime" else "")


FRAMING_TEXT = {
    "full_body": "构图：完整身形入镜，头顶到脚有合理留白；主角仍可辨，肢体和脚部连接自然。",
    "wide": "构图：环境远景，人物与空间关系清楚，场景服务故事；按动作决定人物占比，避免脸部失真。",
    "close_up": "构图：头肩近景，从头顶到胸口，主角的脸占画面高度约三分之一。",
    "waist_up": "构图：景别严格只到腰部，不出现腿和脚。",
    "knee_up": "构图：画面从头顶到膝盖，不出现小腿和脚。",
    "mid_interactive": "构图：互动中景，从头顶到大腿中部，不出现脚。",
}
HANDS_FRAMING_TEXT = "构图：手部与动作局部特写，主角头部在画框外。"
BACK_CLOSE_UP_TEXT = "构图：背后近景，从后脑到肩背。"


def framing_text(scene: dict) -> str:
    # Face-sized framing lines would contradict a faceless shot and invite a face back in.
    presence = scene["user"].get("presence", "face")
    if presence == "hands":
        return HANDS_FRAMING_TEXT
    if presence == "back" and scene["framing"] == "close_up":
        return BACK_CLOSE_UP_TEXT
    return FRAMING_TEXT[scene["framing"]]


# Optional; eye level is the default and gets no line.
CAMERA_TEXT = {"high": "机位：略俯拍。", "low": "机位：略仰拍。", "side": "机位：从主角侧前方约四十五度拍。"}
POSITION_TEXT = {"left": "画面左侧", "right": "画面右侧", "center": "画面中间"}
CAST_REQUIRED_MODES: Tuple[str, ...] = ("classic_presence", "archetype")
# Short labels for the head line when a card gives no visible_parts.
PRESENCE_TEXT = {
    "hand": "只露一只手",
    "shadow": "只以墙上或地上的影子出现",
    "back": "只露背影",
    "cropped": "被画框裁切、只露肩膀以下",
    "peek": "只从遮挡物边缘露出有辨识度的局部",
    "cover": "用道具遮住脸",
}
# Strict no-face mechanism per presence (bakeoff v2 winner): one short clause closing the character line.
NO_FACE_MECHANISM = {
    "hand": "头部和躯干在画外；手与前臂只露本张写明的范围。",
    "shadow": "本人在画外；影子落在主角附近的墙面或地面，与真人等大，方向与光源一致，没有面部细节。",  # run 110 giant floating shadow
    "back": "严格背对镜头，不回头、不露侧脸。",
    "cropped": "头部在画框外。",
    "peek": "头部藏在遮挡物后，只露帽饰、手或尾巴等局部。",
}
# Keep the card's chosen occluder; a fixed example must not add another backdrop.
COVER_MECHANISM = {
    "full_head": "身体藏在本张写明的遮挡物后，只露手和袖口；道具比头大一圈、密实不透光，头顶、头发、双耳、两侧和下巴都在道具后。",
    # The crown peek is optional: low headwear (Zhuge Liang, runs 114-118) may stay hidden.
    "face": ("身体藏在本张写明的遮挡物后，冠帽等头饰顶可露在道具上方，其余只露手和袖口；"
             "道具密实不透光，正好盖住眼、鼻、嘴、两颊和下巴。"),
}
RETIRED_PRESENCE = {"side_profile": "出场方式 side_profile 已停用：请改用 back（背影）或 cropped（头在画框外）"}
PROMPT_RECOMMENDED_CHARS = 760  # advisory whitespace-free count; never truncate a prompt
# Closing lines follow the bakeoff v2 winner: two sentences instead of the old face/no-mix stack.
# "The character's face is an original design" was dropped: it invites drawing a face.
# The user's face may turn to three-quarter view so five shots can differ in pose.
CAST_CLOSE_TEXT = ("主角不长出角色五官，不混脸，脸清楚受光（正脸或四分之三侧脸，五官完整可见），手、道具和饰品不遮挡五官。"
                   "角色绝不露脸，镜面、反光和背景里也不露；不用黑脸、模糊脸或正面无脸人形代替。")
SHY_TEXT = "角色害羞，脸不出现在画面里，也不出现正面朝向的无脸人形或脸部黑影。"
SOLO_TEXT = "画面中只有主角一个可辨认的人物；背景里如有路人，只能是虚构的、看不清脸的远景小人。"
FACE_TEXT = "主角的脸清楚受光（正脸或四分之三侧脸，五官完整可见），手、道具和饰品不遮挡五官。"
# A single frontal photo holds the face only near frontal (2026-10-22 pose study); shots that need a
# turned head show the user without a face instead of a drifting profile.
USER_PRESENCE_TEXT = {
    "back": "本张主角背对镜头，只露后脑、头发、肩背与动作，不露脸；回头最多转到肩线，看不见五官、不露侧脸；不出现正面无脸人形或脸部黑影。",
    "hands": "本张只拍主角的双手与动作局部，头部在画框外，不露脸；手的肤色、体型与本人一致。",
}
CAST_NO_MIX_TEXT = "主角不长出角色五官，不混脸。"
CAST_HIDDEN_TEXT = "角色绝不露脸，镜面、反光和背景里也不露；不用黑脸、模糊脸或正面无脸人形代替。"
# Character design follows the chosen scene; rights are assessed for the actual use, not by an IP category ban.
ADAPTATION_TEXT = "角色造型按本套已确认的角色、时期、服饰与道具描述呈现，保持套图中的造型连续。"
ORIGINAL_TEXT_ADAPTATION = "本玩法以原著描写为造型依据；只有用户明确选择其他改编版本时才采用相应造型。"
GENRE_TEXT = "按本套选定的片型、年代与情节组织分镜。"
CHECKIN_TEXT = "没有任何动漫、电影或电视剧的角色、海报、周边或标志。"
CLEAN_TEXT = "无叠加文案、品牌、水印或拼贴分格；场内必要的印刷或手写痕迹依本镜。"
CHAIN_TEXT = ("附图 {n} 是这套照片的第 1 张成片：{keep}、场景的美术风格与色调必须与附图 {n} 一致"
              "（本条另有说明的除外）；主角的脸以附图 1 为准，不借附图 {n} 的构图。")
USER_PHOTO_TEXT = ("是同一位真实成年人（以下称“主角”）的照片：身份参考采用主角的脸、发型，"
                   "不借照片里的衣服、饰品和背景；保留主角自己的脸型、眼形、鼻形、唇形，"
                   "不美化、不瘦脸、不放大眼睛、不改成网红脸。")
USER_PHOTO_RESTYLED = ("是同一位真实成年人（以下称“主角”）的照片：脸部身份参考采用主角的脸，"
                       "不借照片里的发型、衣服、饰品和背景；保留主角自己的脸型、眼形、鼻形、唇形，"
                       "不美化、不瘦脸、不放大眼睛、不改成网红脸。")
USER_PHOTO_ANIME_RESTYLED = ("是同一位真实成年人（以下称“主角”）的照片：把主角用日式动画画风重绘，"
                             "但保留主角可辨认的脸型、眼形、鼻形、唇形，让熟人一眼认出是本人；"
                             "不借照片里的发型、衣服、饰品和背景，不美化成网红脸。")
USER_PHOTO_OPERA = ("是同一位真实成年人（以下称“主角”）的照片：脸部身份参考采用主角的脸，"
                    "不借照片里的发型、衣服、饰品和背景（头饰由戏曲扮相决定）；保留主角自己的脸型、眼形、鼻形、唇形，"
                    "不美化、不瘦脸、不放大眼睛。")
USER_PHOTO_ANIME = ("是同一位真实成年人（以下称“主角”）的照片：把主角用日式动画画风重绘，"
                    "但保留主角可辨认的脸型、眼形、鼻形、唇形、发型，让熟人一眼认出是本人；"
                    "不借照片里的衣服、饰品和背景，不美化成网红脸。")
USER_PHOTO_FACELESS = ("是同一位真实成年人（以下称“主角”）的照片：本张主角不露脸，参考主角可见的发色、肤色，"
                       "不借照片里的衣服、饰品和背景，不画出主角的五官。")
BODY_REFERENCE_TEXT = ("身形仅参考照片中清楚可见或本张描述已确认、且当前画面需要的部分；"
                       "不推断遮挡、未入镜部位或衣下尺寸。以本张明确的身形描述为准，"
                       "明确调整仅覆盖对应部位，其他已确认特征保留；"
                       "服装支撑、姿势与镜头造成的外观变化不等于身体改变。")
EXPRESSION_TEXT = ("表情按本张动作中的明确描述执行，未说明时沿用自拍表情；"
                   "不因表情改变脸型和五官骨相。")


def hard_constraints(play_mode: str, has_cast: bool, scene: Optional[dict] = None) -> Tuple[str, ...]:
    """Fixed lines appended to every prompt; cards can neither add to nor remove them."""
    tail = (GENRE_TEXT,) if play_mode == "genre_scene" else (CHECKIN_TEXT,) if play_mode in SOLO_LIFE_MODES and not has_cast else ()
    presence = ((scene or {}).get("user") or {}).get("presence", "face")
    if has_cast:
        adaptation = ORIGINAL_TEXT_ADAPTATION if play_mode == "original_text" else ADAPTATION_TEXT
        close = CAST_CLOSE_TEXT if presence == "face" else CAST_NO_MIX_TEXT + USER_PRESENCE_TEXT[presence] + CAST_HIDDEN_TEXT
        return (close, adaptation, CLEAN_TEXT) + tail
    if play_mode == "original_text":
        tail += (ORIGINAL_TEXT_ADAPTATION,)
    face = FACE_TEXT if presence == "face" else USER_PRESENCE_TEXT[presence]
    return (SOLO_TEXT, face, CLEAN_TEXT) + tail


SHEET_STATUSES: Tuple[str, ...] = ("temp_draft", "temp_confirmed")
SHEET_TEXT = {
    "head": "角色头部定妆表，浅灰色纯色背景，同一角色的正面、四分之三侧面、侧面三个头像并排，造型与质感按角色卡的确认描述呈现。",
    "body": "角色全身定妆表，浅灰色纯色背景，同一角色正面与背面全身并排，造型与质感按角色卡的确认描述呈现。",
}
SHEET_REF_TEXT = {
    "head": "附图 1 是同一角色另一时期的头部定妆表，只借脸部骨相、五官与毛发质感；与下列文字冲突时以文字为准；不借灰底和分格版式。",
    "body": "附图 1 是该角色本时期的头部定妆表，脸、毛发与头饰必须与附图 1 一致；不借灰底和分格版式。",
}
SHEET_CLOSING = "角色造型与确认描述一致，不擅自加入真人演员的面部特征。无文字、无水印。"


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def current_revision(scene: dict) -> int:
    revisions = scene.get("revisions") or []
    return revisions[-1]["n"] if revisions else 1


def _figure_label(indices: List[int]) -> str:
    return "附图 " + "、".join(str(i) for i in indices)


def _check_names(texts: Sequence[str], names: Sequence[NameEntry]) -> None:
    hits = sorted({h.matched for t in texts if t for h in scan(t, names)})
    if hits:
        raise CardError("blocked_name", "提示词中出现真实演员姓名：" + "、".join(hits))


def _select_refs(user_photos: Sequence[Path], sheets: List[Tuple[str, Path, int]],
                 scene_ref: Optional[Path], chain_ref: Optional[Path], max_refs: int,
                 mood_ref: Optional[Path] = None, pet_ref: Optional[Path] = None):
    """Trim to max_refs: scene ref, body sheets, mood ref, 2nd user photo, then head sheets.

    The first user photo, the pet photo and the set's chain image are never dropped (spec v4 §0 F9).
    """
    user = list(user_photos)[:MAX_USER_PHOTOS]
    kept = list(sheets)
    fixed = (1 if chain_ref is not None else 0) + (1 if pet_ref is not None else 0)

    def total() -> int:
        return (len(user) + len(kept) + (1 if scene_ref is not None else 0)
                + (1 if mood_ref is not None else 0) + fixed)

    while total() > max_refs:
        bodies = [i for i, s in enumerate(kept) if s[0] == "body"]
        if scene_ref is not None:
            print(f"提示：参考预算未采用场景图：{scene_ref}；本次请求不包含该实景参考", file=sys.stderr)
            scene_ref = None
        elif bodies:
            kept.pop(bodies[-1])
        elif mood_ref is not None:
            print(f"提示：参考预算未采用氛围参考图：{mood_ref}；本次请求不包含该参考", file=sys.stderr)
            mood_ref = None
        elif len(user) > 1:
            user.pop()
        elif kept:
            kept.pop()
        else:
            raise CardError("too_many_refs", f"用户照、宠物照与套图参考已超过参考图上限 {max_refs}")
    dropped = [str(p) for p in user_photos if p not in user] + [str(p) for _, p, _ in sheets if p not in [v[1] for v in kept]]
    if dropped:
        print("提示：参考预算未采用：" + "、".join(dropped), file=sys.stderr)
    return user, kept, scene_ref, mood_ref


def _load_cast(scene: dict, characters: Dict[str, dict]):
    cast = []
    for member in scene["characters"]:
        card = characters.get(member["character_id"])
        if card is None:
            raise CardError("unknown_character", f"缺少角色卡：{member['character_id']}")
        require_valid(card, "character")
        if card["status"] not in ("gold", "temp_confirmed"):
            raise CardError("character_not_confirmed", f"角色卡尚未确认：{card['name']}")
        cast.append((member, card, find_variant(card, member["variant_id"])))
    return cast


def _body_sha256(prompt: str, refs: List[str]) -> str:
    body = {"prompt": prompt, "referenced_image_paths": refs}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def props_shown(scene: dict) -> List[str]:
    """Text-based prop candidates for chaining; not evidence of visibility in the rendered image."""
    # setting is excluded: a prop named in the set dressing may be cropped out of image 1.
    text = "".join([scene.get("props", ""), scene["user"]["action"], scene["user"].get("costume", "")]
                   + [m["action"] + m.get("visible_parts", "") for m in scene["characters"]])
    return [p["name"] for p in scene.get("prop_specs") or [] if p["name"] in text]


def _visible(member: dict) -> str:
    return member.get("visible_parts") or PRESENCE_TEXT[member["character_presence"]]


def _character_text(member: dict, card: dict) -> str:
    """One sentence: which part shows, where from, doing what (POC runs 27-30).

    The full character card is never injected: it invites a half-body stand-in.
    """
    presence = member["character_presence"]
    mechanism = COVER_MECHANISM[member["cover_level"]] if presence == "cover" else NO_FACE_MECHANISM.get(presence)
    # identity_features are never appended: they describe the face this character must not show.
    if member.get("visible_parts"):
        text = f"{card['name']}只局部入镜：{member['visible_parts']}，{member['action']}"
    else:
        text = f"{card['name']}只局部入镜（{PRESENCE_TEXT[presence]}）：{member['action']}"
    text += f"；局部或影子位于{POSITION_TEXT[member['position']]}"
    if member.get("expression"):
        text += f"；情绪通过动作表达：{member['expression']}，不因此画出脸"
    return text + (f"；{mechanism}" if mechanism else "。")


def _check_user(mode: str, user: dict) -> None:
    if (user["mode"] == "in_story" or mode == "opera_costume") and not user.get("role"):
        raise CardError("missing_role", "入戏或戏曲扮相必须指定剧中身份或行当")
    if user["mode"] == "fitting" and not (user.get("costume") or user.get("outfit")):
        raise CardError("missing_costume", "试装需要说明本次衣装")


def check_retired_presence(scene: dict) -> None:
    """Run before schema validation, so an old card gets a migration hint instead of a bare enum error."""
    for member in scene.get("characters") or []:
        presence = member.get("character_presence") if isinstance(member, dict) else None
        if isinstance(presence, str) and presence in RETIRED_PRESENCE:
            raise CardError("presence_retired", RETIRED_PRESENCE[presence])


def check_cover_level(scene: dict) -> None:
    for member in scene["characters"]:
        is_cover = member["character_presence"] == "cover"
        if is_cover and "cover_level" not in member:
            raise CardError("cover_level_required", "道具遮脸要写 cover_level：full_head（全遮头部）或 face（只遮整张脸，帽冠顶可露）")
        if not is_cover and "cover_level" in member:
            raise CardError("cover_level_only_for_cover", "只有 character_presence 为 cover 时才写 cover_level")


def check_user_presence(scene: dict) -> None:
    """A faceless shot cannot also ask for a side-front camera."""
    presence = scene["user"].get("presence", "face")
    if presence == "face":
        return
    if scene.get("camera_angle") == "side":
        raise CardError("presence_camera_conflict", "主角不露脸的镜头不能用侧前方机位；请去掉 camera_angle=side 或改回露脸")


def compile_request(scene: dict, characters: Dict[str, dict], user_photos: Sequence[Path],
                    sheet_resolver: Callable[[dict], Path], names: Sequence[NameEntry],
                    scene_ref: Optional[Path] = None, run_id: Optional[str] = None,
                    max_refs: int = MAX_REFS, chain_ref: Optional[Path] = None,
                    set_info: Optional[dict] = None, chain_props: Sequence[str] = (),
                    mood_ref: Optional[Path] = None, pet: Optional[dict] = None) -> dict:
    """chain_props: prop names already shown on image 1; on later shots they follow the chain image."""
    check_retired_presence(scene)
    require_valid(scene, "scene")
    check_cover_level(scene)
    check_user_presence(scene)
    if scene["status"] != "user_confirmed":
        raise CardError("scene_not_confirmed", "分镜卡尚未经用户确认")
    if scene["play_mode"] == "pet_daily":
        if scene["characters"]:
            raise CardError("pet_daily_no_cast", "和宠物过日常只拍你和它，不加角色")
        if pet is None:
            raise CardError("pet_daily_needs_pet", "和宠物过日常需要一张宠物照")
        if not scene.get("pet"):
            raise CardError("pet_daily_every_shot", "和宠物过日常每张都要有宠物")
    if scene.get("pet") and pet is None:
        raise CardError("pet_without_ref", "这张写了宠物，但套图卡没有宠物照")
    if pet is not None and set_info is not None and set_info["index"] == 1 and not scene.get("pet"):
        raise CardError("pet_missing_on_cover", "带宠物的套图，封面必须有宠物")
    pet_ref = pet["ref"] if pet is not None and scene.get("pet") else None
    if not user_photos:
        raise CardError("no_user_photo", "至少需要 1 张用户正脸照")
    mode = scene["play_mode"]
    head = style_text(scene)
    user = scene["user"]
    _check_user(mode, user)
    if mode in CAST_REQUIRED_MODES and not scene["characters"]:
        raise CardError("cast_required", "这个玩法需要至少一位害羞在场的角色")
    cast = _load_cast(scene, characters)

    sheets = [(kind, sheet_resolver(variant["sheets"][kind]), i)
              for i, (_, _, variant) in enumerate(cast)
              for kind in ("head", "body") if kind in (variant.get("sheets") or {})]
    user_refs, kept, ref, mood = _select_refs(user_photos, sheets, scene_ref, chain_ref, max_refs, mood_ref, pet_ref)
    refs = list(user_refs) + [p for _, p, _ in kept] + ([ref] if ref is not None else [])
    refs += [mood] if mood is not None else []
    refs += [pet_ref] if pet_ref is not None else []
    refs += [chain_ref] if chain_ref is not None else []

    specs = scene.get("prop_specs") or []
    narrative = [scene["setting"], scene.get("props", ""), user["action"],
                 user.get("role", ""), user.get("outfit", ""), user.get("costume", ""),
                 scene.get("film_context", ""), scene.get("lighting", ""), scene.get("cinematography", ""),
                 scene.get("pet", ""), (pet or {}).get("look", "")]
    narrative += [p["name"] + p["spec"] for p in specs]
    who = "、".join(card["name"] for _, card, _ in cast)
    parts = "、".join(f"{card['name']}的局部（{_visible(member)}，看不到脸）" for member, card, _ in cast)
    lines = [head + (f"画面里有主角，以及{parts}。" if cast else "画面里只有主角一个主要人物。")]
    photo_text = ((USER_PHOTO_ANIME_RESTYLED if user.get("hairstyle") or mode == "opera_costume" else USER_PHOTO_ANIME)
                  if subject_style(scene) != "photographic"
                  else USER_PHOTO_OPERA if mode == "opera_costume"
                  else USER_PHOTO_RESTYLED if user.get("hairstyle") else USER_PHOTO_TEXT)
    if subject_style(scene) == "animation_3d":
        photo_text = photo_text.replace("日式动画画风", "三维动画造型与渲染风格")
    faceless = user.get("presence", "face") != "face"
    if faceless:
        # Face, expression and "face follows image 1" lines would pull a face back into a back/hands shot.
        photo_text = USER_PHOTO_FACELESS
    lines.append(_figure_label(list(range(1, len(user_refs) + 1))) + " " + photo_text
                 + ("" if faceless else EXPRESSION_TEXT))
    lines.append(BODY_REFERENCE_TEXT)
    next_index = len(user_refs) + 1
    for i, (member, card, variant) in enumerate(cast):
        mine = [s for s in kept if s[2] == i]
        if mine:
            indices = list(range(next_index, next_index + len(mine)))
            next_index += len(mine)
            lines.append(f"{_figure_label(indices)} 是角色“{card['name']}”（{variant['label']}）的定妆表，"
                         f"只借露出部分的毛发、衣装与质感，不据此画出角色的其他部分，不借脸，不借灰底和分格版式。")
        narrative += [variant["identity_features"], variant["costume"], variant.get("props", ""),
                      variant.get("exclusions", ""), variant["label"],
                      member["action"], member.get("expression", ""), member.get("visible_parts", "")]
    if ref is not None:
        lines.append(f"附图 {next_index} 是场景参考，只借环境与光线，不借其中的任何人物、文字和标志。")
        next_index += 1
    if mood is not None:
        lines.append(f"附图 {next_index} 是氛围参考，只借光线方向、明暗和色调；"
                     f"不借构图、景别和机位，不借其中的人物、文字、标志和具体物件。")
        next_index += 1
    if pet_ref is not None:
        kind = pet["kind"]
        lines.append(f"附图 {next_index} 是主角自己的{kind}：画面里的{kind}就是它，"
                     + (f"它是{pet['look']}，" if pet.get("look") else "") + "毛色、花纹、脸型、"
                     f"眼睛颜色和体型与附图一致；不借照片里的背景、人手、物件和姿势。{kind}在这张里：{scene['pet']}。"
                     + ("" if subject_style(scene) == "photographic" else "按本张画风画它，但毛色花纹和眼睛颜色不变。"))
        next_index += 1
    chain_line_index = None
    if chain_ref is not None:
        # "Unless stated here" lets one shot change a costume piece (crown taken off, POC run 30).
        # Add only wardrobe here; prop names are resolved after this shot's text is rendered.
        keys = "、".join(user.get("costume_keys") or [])
        keep = "主角的妆发与服装" + (f"（{keys}）" if keys else "")
        chain = CHAIN_TEXT.format(n=next_index, keep=keep)
        chain_line_index = len(lines)
        lines.append(chain.replace("主角的脸以附图 1 为准", "主角不露脸") if faceless else chain)
        if pet is not None and pet_ref is None:
            lines.append(f"这张画面里没有{pet['kind']}，不要从附图 {next_index} 带出{pet['kind']}。")
    lines.append(f"场景：{scene['setting']}。")
    if scene.get("lighting"):
        lines.append(f"光线：{scene['lighting']}。")
    if mode == "opera_costume":
        lines.append(f"主角采用{user['role']}的戏曲扮相" + {"back": "，头面与衣装按本张说明的穿戴阶段呈现。", "hands": "，可见袖口按本张衣装说明呈现。"}.get(
            user.get("presence", "face"), "，五官保持本人可辨。"))
    elif user["mode"] == "fitting":
        lines.append(f"主角试装成{user.get('role') or who or '本次主题造型'}，保留本人身份。")
    elif user["mode"] == "traveler" and mode == "pet_daily":
        lines.append(f"主角在自己的日常生活里，和自己的{pet['kind']}在一起。")
    elif user["mode"] == "traveler":
        lines.append("主角以来访者身份出现。")
    else:
        lines.append(f"主角作为{user['role']}参与剧情，保持本人可辨。")
    clothes = list(dict.fromkeys(user[k] for k in ("costume", "outfit") if user.get(k)))
    if clothes:
        lines.append("主角衣装：" + "；".join(clothes) + "。")
    else:
        lines.append("主角衣装：" + ("本套确认的戏服与头面" if mode == "opera_costume" else "符合本次身份与场景的服饰") + "。")
    lines.append(f"发型：{user['hairstyle']}。" if user.get("hairstyle") else "保留主角原有发型轮廓，头饰按本套造型。")
    lines.append(f"妆面：{user['makeup']}；保持本人可辨。" if user.get("makeup") else "保留自拍中的原有妆面，不另加角色妆。")
    if scene.get("cinematography"):
        lines.append(f"摄影设计：{scene['cinematography']}。")
    # The character never gets a position of its own: its action says where the part comes from.
    for member, card, variant in cast:
        text = _character_text(member, card)
        if mode == "archetype" and variant.get("exclusions"):
            # Original characters rely on exclusions to stay clear of existing IP marks (audit #20).
            text = text[:-1] + f"；排除：{variant['exclusions']}。"
        lines.append(text)
    lines.append(f"站位与动作：主角在{POSITION_TEXT[user['position']]}，{user['action']}。")
    if scene.get("props"):
        lines.append(f"道具：{scene['props']}。")
    # Only props this shot actually mentions: a listed but absent prop gets drawn in (reshoot run 50).
    # Match against all emitted shot text (including pet, hair and makeup), excluding
    # the generated chain line so it cannot make an absent prop appear relevant.
    prop_context = "\n".join(line for i, line in enumerate(lines) if i != chain_line_index)
    shown = [p for p in specs if p["name"] in prop_context]
    unused = [p['name'] for p in specs if p not in shown]
    if chain_line_index is not None:
        inherited = [p["name"] for p in shown if p["name"] in chain_props]
        if inherited:
            chain = CHAIN_TEXT.format(n=next_index, keep=keep + "".join("、" + n for n in inherited))
            lines[chain_line_index] = chain.replace("主角的脸以附图 1 为准", "主角不露脸") if faceless else chain
            lines.append("道具仅参考首图中正确且可见的外观；本张数量、归属、状态与明确修改以本张说明为准。")
    if unused:
        print('提示：本张正文未提及这些道具名，规格不会进入提示词：' + '、'.join(unused)
              + '；若是同一道具，请统一 prop_specs.name 与正文名称。', file=sys.stderr)
    if shown:
        # Keep this shot's explicit spec even when its appearance has a chain reference.
        lines.append("道具规格：" + "；".join(f"{p['name']}——{p['spec']}" for p in shown) + "。")
    lines.append(framing_text(scene))
    if scene.get("camera_angle"):
        lines.append(CAMERA_TEXT[scene["camera_angle"]])
    lines.extend(hard_constraints(mode, bool(cast), scene=scene))
    prompt = "\n".join(lines)
    size = len("".join(prompt.split()))
    # Line by line: names are compacted, so two adjacent lines must not join into a false hit.
    _check_names(narrative + prompt.split("\n"), names)

    ref_paths = [str(Path(p)) for p in refs]
    request = {
        "schema_version": "1",
        "run_id": run_id or new_run_id(),
        "prompt": prompt,
        "referenced_image_paths": ref_paths,
        "card_ref": {"scene_id": f"{scene['ip']}/{scene['id']}", "revision": current_revision(scene)},
        "max_refs": max_refs,
        "sha256": _body_sha256(prompt, ref_paths),
    }
    if set_info is not None:
        request["set"] = dict(set_info)
    require_valid(request, "request")
    if size > PROMPT_RECOMMENDED_CHARS:
        shot = f"第 {set_info['index']} 张" if (set_info or {}).get("index") else "这张"
        # Diagnostic only: keep request schema, integrity hash and CLI JSON stdout unchanged.
        print(f"提示：{shot}提示词 {size} 字，超过建议长度 {PROMPT_RECOMMENDED_CHARS} 字；"
              "已完整保留，未截断。这是长度提醒，不会自动生图。", file=sys.stderr)
    return request


def _sheet_ref(card: dict, variant: dict, kind: str, ref_variant: Optional[str],
               sheet_resolver: Callable[[dict], Path]) -> Optional[Path]:
    """Body sheets always follow this variant's head; head sheets may borrow another variant's head."""
    if kind == "body":
        if ref_variant is not None:
            raise CardError("bad_sheet_ref", "全身定妆表固定参考本时期的头部定妆表，不接受其他参考")
        head = (variant.get("sheets") or {}).get("head")
        if head is None:
            raise CardError("head_sheet_first", f"请先生成并挂上 {variant['label']} 的头部定妆表")
        return sheet_resolver(head)
    if ref_variant is None:
        return None
    if ref_variant == variant["variant_id"]:
        raise CardError("bad_sheet_ref", "参考时期不能是本时期")
    head = (find_variant(card, ref_variant).get("sheets") or {}).get("head")
    if head is None:
        raise CardError("missing_sheets", f"参考时期 {ref_variant} 还没有头部定妆表")
    return sheet_resolver(head)


def compile_sheet_request(card: dict, variant_id: str, kind: str,
                          sheet_resolver: Callable[[dict], Path], names: Sequence[NameEntry],
                          ref_variant: Optional[str] = None, run_id: Optional[str] = None) -> dict:
    """Compile one temporary character sheet (head or body) into a sheet request."""
    require_valid(card, "character")
    if card["status"] not in SHEET_STATUSES:
        raise CardError("sheet_not_temp", f"只有临时角色卡可以生成定妆表：{card['name']}")
    if kind not in SHEET_TEXT:
        raise CardError("unknown_sheet_kind", f"定妆表只有 head 与 body 两种：{kind}")
    variant = find_variant(card, variant_id)
    ref = _sheet_ref(card, variant, kind, ref_variant, sheet_resolver)
    lines = [SHEET_TEXT[kind]]
    if ref is not None:
        lines.append(SHEET_REF_TEXT[kind])
    lines.append(f"角色：{card['name']}（{variant['label']}）。固定辨识特征：{variant['identity_features']}。")
    if kind == "body":
        lines.append(f"衣装：{variant['costume']}。")
        if variant.get("props"):
            lines.append(f"随身道具：{variant['props']}。")
    if variant.get("exclusions"):
        lines.append(f"排除：{variant['exclusions']}。")
    lines.append(SHEET_CLOSING)
    prompt = "\n".join(lines)
    _check_names([prompt], names)
    refs = [str(ref)] if ref is not None else []
    request = {
        "schema_version": "1",
        "kind": "sheet",
        "run_id": run_id or new_run_id(),
        "prompt": prompt,
        "referenced_image_paths": refs,
        "card_ref": {"character_id": f"{card['ip']}/{card['id']}", "variant_id": variant_id, "sheet": kind},
        "sha256": _body_sha256(prompt, refs),
    }
    require_valid(request, "sheet_request")
    return request


def compile_edit_request(scene: dict, image: Path, instruction: str,
                         names: Sequence[NameEntry], run_id: Optional[str] = None) -> dict:
    """Use one explicit edit base without importing the storyboard's retake directions."""
    require_valid(scene, "scene")
    if scene["status"] != "user_confirmed":
        raise CardError("scene_not_confirmed", "局部编辑关联的分镜卡尚未经用户确认")
    if not instruction.strip():
        raise CardError("empty_edit_instruction", "请说明本次要修改的内容")
    prompt = ("附图 1 是本次局部编辑的底图，请在这张图上完成以下修改：\n"
              + instruction
              + "\n除本次明确修改项及其必要影响外，保留底图的人物身份、其他衣装、"
                "动作、物件、构图、光线和画幅。陪同角色继续不露脸；不添加叠加文案或水印。")
    _check_names([prompt], names)
    refs = [str(Path(image).resolve())]
    request = {
        "schema_version": "1", "run_id": run_id or new_run_id(),
        "prompt": prompt, "referenced_image_paths": refs,
        "card_ref": {"scene_id": f"{scene['ip']}/{scene['id']}", "revision": current_revision(scene)},
        "max_refs": 1, "sha256": _body_sha256(prompt, refs),
    }
    require_valid(request, "request")
    return request


def write_request(request: dict, run_dir: Path) -> Path:
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "request.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    refs = request['referenced_image_paths']
    if all(Path(p).is_file() for p in refs):
        from .library import sha256_file
        manifest = {'request_sha256': request['sha256'],
                    'references': {p: sha256_file(Path(p)) for p in refs}}
        (run_dir / 'reference-hashes.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return path


def check_request_integrity(request: dict) -> None:
    require_valid(request, 'sheet_request' if request.get('kind') == 'sheet' else 'request')
    if _body_sha256(request['prompt'], request['referenced_image_paths']) != request['sha256']:
        raise CardError('request_tampered', 'request.json 在编译后被改动，请重新编译')


def check_reference_hashes(request_path: Path, request: dict) -> None:
    from .library import sha256_file
    path = Path(request_path).parent / 'reference-hashes.json'
    if not path.is_file():
        raise CardError('references_unverified', '缺少参考图字节记录，请重新编译，不提交生图')
    manifest = json.loads(path.read_text())
    refs = request['referenced_image_paths']
    recorded = manifest.get('references', {})
    if manifest.get('request_sha256') != request['sha256'] or set(recorded) != set(refs):
        raise CardError('reference_changed', '参考图记录与请求不一致，请重新编译')
    if any(not Path(p).is_file() or sha256_file(Path(p)) != recorded[p] for p in refs):
        raise CardError('reference_changed', '参考图字节已变化，请重新确认并编译')
