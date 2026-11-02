# 同角色多系列创作与返回续拍

用户选角色、要多套、说“都拍”、返回继续或需要整理版本时读取。只拍一套仍可沿用旧流程；不强制先建立项目。

## 用户旅程与职责

角色项目（如“我和孙悟空”）包含多个主题系列（剧组、练功、美食），一个系列可有多套五张作品，单张可有多个重拍版本。五张是一套的单位，不是整个角色项目的上限。

1. 已有具体需求直接准备。只说喜欢某角色，先拍一套；交付后问“要不要接着拍？”并给3个有区别的新系列，每个说清体验、摄影方向及与其他系列的区别，接受自由创意；用户选中才加进selection，再`project-continue`登记。写策划读series-creation.md。
2. 用户可选一套、多套或全部。先在同一条消息里列出本次所选每套的五张分镜（每套一行）和总范围，例如3套15张。“全部”只指当时展示并确定的列表；新提案不会自动加入。
3. 方案确认与生成意图分开。将本次明确选择的set_id依序写入selection；该列表仅记录范围，不是生图授权。保存方案不compile、不claim。
4. 明确生成后统一核对素材、同意和所选范围，逐套执行；套内一次拍完五张，每套结束停下交付，用户说“继续”后用 `CLI project-continue --workspace WS --set-id 下一套` 登记再拍（D12）。各套使用自己的首图维持连续性；项目偏好是默认值，系列明确衣装、画风和摄影方向优先，不跨套强制继承首图。
5. 按系列交付，区分已生成、已交付、用户已接受。列出问题和待决定内容。修改只影响指定套图与镜头，旧版保留，新版不自动选用。
6. 返回时读取指定私有工作区的project.json和project-status，简短展示已拍/待拍/待修改，再回应当前要求。不重新索要有效素材、不扫描其他工作区、不猜测用户接受范围。临时目录可能被清理；长期续拍须使用用户指定的持久私有工作区。

例如用户说“后台、练功、美食都要，先看看”：提供三套分镜，说明共15张，停在准备。用户随后说“按这三套拍”：在照片等条件齐备时依序执行，不再问三次。用户说“下次继续美食”：先读状态，沿用照片和角色版本；已有任务只提交未提交部分，新的美食续作另建set_id。

## 本地索引格式

项目索引本身须是WS内outputs/以外的.json文件（默认WS/project.json），否则project-status与project-continue返回invalid_project。所有路径相对WS（也接受WS内绝对路径），包括素材和角色卡引用；不把私人文件放进运行包。库角色需要时将对应文字卡复制到WS引用，不扫描整库。使用schema/project.schema.json校验。

```json
{
  "schema_version": "1",
  "project_id": "me-and-po",
  "title": "我和孙悟空",
  "character": {"name": "孙悟空", "version": "原著", "cards": ["characters/wukong.json"]},
  "photo_refs": ["input/identity.png"],
  "preferences": {"subject": "photographic", "hairstyle": "沿用本人"},
  "series": [
    {"series_id": "studio", "title": "剧组探班", "brief": "参与一次拍摄；片场抓拍，设备与拍摄活动可读",
     "sets": [{"set_id": "studio-01", "card": "cards/studio-01.json"}]},
    {"series_id": "training", "title": "初次练功", "brief": "尝试与学习；用步法和身体反应推进",
     "sets": [{"set_id": "training-01", "card": "cards/training-01.json"}]},
    {"series_id": "food", "title": "一起做饭", "brief": "从选食材到开饭；轻松生活写真",
     "sets": [{"set_id": "food-01", "card": "cards/food-01.json"}]}
  ],
  "selection": ["studio-01", "training-01", "food-01"]
}
```

尚未展开分镜的系列可以sets=[]；只有已登记具体套图才可进入selection。不使用通配符或“all”。系列及套图ID唯一。一个系列的新套图追加到sets，不覆盖旧卡。准备、确认或选版后写完整有效索引，再调用只读校验：

```bash
CLI project-status --workspace WS --project project.json
```

该命令不会写文件、提交或自动恢复，也不验证对话授权。结构错误返回invalid_project；引用或结果不一致返回project_needs_review和issues（退出码2）。正常查询返回project_status；账本已记录的失败不一定是索引错误，仍须检查selection.pause_before_next_set。selection提供计划张数、生成状态计数、选用版交付/接受数量及未提交索引；unsubmitted是事实清单，不是可以跳过前置条件的执行队列。

缺文件或结果无法关联时保持unknown/待整理；不从全局generated_images挑最新图补位。未建立项目的旧套图照常工作；用户明确要求整理时，仅登记确认属于本项目的套图。

## 重拍与选版

原版从各套账本自动关联，不重复登记。重拍用单张compile，局部修改用compile-edit指定底图；两者沿用native/deliver流程。必须在编译产生请求后、调用原生生图前，将run_id与实际scene_card持久化到对应set的shots.candidates；然后才调用并交付。这样中断后仍能找到该次尝试。登记候选时保留当前选版；下面包含selected_run_id的示例仅用于用户之后明确选用新版：

```json
"shots": [{
  "index": 3,
  "candidates": [{"run_id": "20261017-120000-abcdef", "scene_card": "cards/food-03-r2.json"}],
  "selected_run_id": "20261017-120000-abcdef"
}]
```

scene_card是该次重拍实际卡片，编号/修订须与请求匹配。只登记候选时不填selected_run_id，保持原版；用户明确选版才填所选run_id。显式null表示暂不选用。候选不自动替换旧版，也不自动继承accepted。验收仍由record-verdict记录，project-status按所选版读取原始记录。仅被选用且五张均有匹配交付、自检和accepted的套图，才能显示complete。

已关联重拍缺少交付记录时，查询报告project_retake_unresolved并暂停当前范围，原版的接受记录保留。先核对本次调用是否提交以及实际结果，不能按普通pending重试。确认成功则补齐原有交付；确认失败或未提交则如实报告，用户另定补拍或继续其他系列的范围，保留该候选作为待整理记录，不伪造交付来消除提示。

## 多套执行、异常与继续

始终使用当前宿主既有流程。Codex依次compile-shot→内置imagegen→set-record，再检查与交付；不通过API或新后台调度器执行。

- 本次selection顺序就是套图顺序；每套五张。素材同意有效则复用，变化时按实际影响核对。
- 当前套首张失败取消余下四张。后续单张明确失败不重试，按单套既有流程处理余下已授权镜头；每套结束都暂停，报告成功/失败/未提交，等用户说继续。
- claimed但没有可核对结果、素材变化、账本异常或调用结果未知时立即停下核对，不把claimed改成pending。
- 用户明确要求继续时，重新明确剩余范围：在selection中保留拟继续的套图，已成功项仍由账本排除；只执行pending并满足首图等前置条件的镜头。历史失败套仍留在项目中；failed/rejected/cancelled不自动恢复。指定补拍才建新的请求或套图。
- 历史范围里的失败会使pause_before_next_set为true。不能通过悄悄删掉失败项冒充无异常；只有用户明确继续后才更新本次范围。当前选中套图或共用素材的缺失/不一致须先核对；未选历史系列缺失如实保留为待整理，不阻断无关联的新系列，也不把它说成已修复。退出码2时查看具体issues及selection.pause_before_next_set，不把所有历史问题当作本次不能创作。

除 project-continue 登记门（generate-set 与 compile-shot 第 1 张会检查）外，项目索引不提供原生工具提交前硬拦；总范围和停止规则由技能执行并留账。内部调用计数不等于服务商账单。
