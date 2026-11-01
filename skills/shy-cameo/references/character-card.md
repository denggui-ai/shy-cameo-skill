# 角色卡与临时定妆表

角色卡必须符合 `schema/character-card.schema.json`。金牌角色在 `library/characters/<ip>/<id>/card.json`，定妆表是 GitHub Release 资产；新角色在 `WS/characters/<ip>-<id>/` 写临时卡。

## 动画角色候选

先写 `temp_draft` 文字角色卡；用户确认造型后可记 `temp_confirmed`，不以制作定妆表为必经门。作品、角色及时期准确记录，不强制成年、不把已有角色改名原创，不沿用“不是卡通”等会抹掉动画身份的排除句。`rights_tier` 只是来源元信息，不是生成许可判断；不能把已有作品写成公版或宣称自动获得商用许可。没有定妆表也可沿用正常编译路径；定妆表仍只在用户明确要求时生成。

## 写临时卡（`status: temp_draft`）
- `identity_features`：只写看得见的固定辨识特征（脸型、毛发、标志性头饰等），依据原著文字和大众公认的标志性元素。有正反面之分的头饰写清朝向（如“紧箍正面纹饰在额前，背后为素面”）。不写任何演员姓名，不写“像某某”。这段只用于定妆表和姓名扫描，不进入套图提示词；套图里要靠什么认出角色，写进分镜卡的 visible_parts 或 action：写卡时先列一份“不露脸也认得出”的局部清单（如阿檀橘红蓬松大尾巴与竹编斗笠；纸鸢背上的折纸大鹤；伞伞墨绿伞身与细长木柄手臂），每张出镜从中取一件；列不出时告诉用户辨识度会弱（D24）。
- `costume` / `props`：原著或大众熟悉的服装与道具，可用文字神似公认形象；按用户选择准确描述，具体使用与公开用途按 `rights-cplus.md` 说明。
- `exclusions`：容易被画错的方向（例如真人照片不变成猴脸，头饰不误画成身体器官；按当前造型选择，不默认排斥动画质感）。
- `rights_tier`：原著公有领域写 `public_domain`；原创影视、动画角色写 `screen_original`；权利方对使用有明确限制、需单独核对的写 `restricted`。三档都只记录来源类别，不据此一概拒绝或认定可用；金牌库收录 `screen_original` 与 `restricted` 前须 Owner 单独审批。
- `status`：新写的卡是 `temp_draft`；用户看过文字造型（或定妆表）点头认可后改 `temp_confirmed`，不需要先做定妆表；`gold` 只用于金牌库模板。
- `lookalike_check.status` 写 `pending`；临时卡不进金牌库。
- 同一角色不同剧情时期各写一个 `variant`。
- `episodes`（可选）：这身造型在原著/作品里出现的 2–3 段情节，如美猴王披挂装→"重返水帘洞（第三回）""竖旗称齐天大圣（第四回）"；取经装→取经路上各难。写套图时 film_context 须写明用了哪一段；用户选的情节与造型对不上时先说明，改造型或改情节。

## 生成临时定妆表（可选；额外图片，须用户明确要求，头部 / 全身各 1 次）

定妆表可选；不随套图自动生成；只有用户明确要求制作时才执行。

定妆表提示词由脚本编译（`compile-sheet`），两个宿主完全相同；不要自己拼提示词。

1. 先确认用户确实要求制作本次定妆表（话术见 `references/dialogue.md`）。头部、全身各算 1 次，逐张生成，失败不自动重试。
2. 头部：`CLI compile-sheet --character <卡片> --variant <时期> --sheet head --workspace WS`，拿到 R（`request_path`）。同一角色已有另一时期的头部定妆表时，可加 `--ref-variant <那个时期>`，让脸保持一致。
3. 生成：Codex 按 `references/backend-codex-native.md` 用 R 生成；Claude Code 用 `CLI generate-exec --request R --workspace WS --authorized-count 1`。之后运行 `CLI verify --request R`。
4. 挂回卡片：`CLI attach-sheet --character <卡片> --variant <时期> --sheet head --image <生成的 PNG 原图> --workspace WS`。脚本按原字节复制，并把卡片状态改回 `temp_draft`。由 attach-sheet 自动完成：同时把该时期的神似检查重置为 pending（换了图就要重新检查）。
5. 全身：重复第 2–4 步，参数改为 `--sheet body`（自动参考本时期的头部定妆表，所以必须先挂好头部）。
6. 把两张定妆表给用户看：确认 → 把卡片 `status` 改为 `temp_confirmed`；不满意 → 重做（用户明确要求重做）或放弃该角色。
