# Codex 内生图约定

## 多套入口

多套先读series-projects.md，按project.json中的本次selection逐套使用下文单套流程。project-status只读汇总，不会提交、恢复或证明授权。首图串联仅限各自套图。当前套明确失败后按既有规则处理完该套再暂停下一套；结果未知、素材变化、账本异常立即核对。明确继续后重新记录剩余范围，不重提成功项、不自动补拍失败项。

动画主题沿用以下同一编译与生成流程，不另造通路、不手改request。三组已测样例见 `animation-themes.md`，不以角色国别或虚构年龄增加门。只准备或验证不授权生图；离线测试不证明成片效果。

0. 只有在取得用户明确授权后才执行以下步骤：明确请求拍摄当前套图即可执行固定五张（见 SKILL.md“用户意图与调用范围”），额外定妆表需用户另行要求（见 `references/character-card.md`）。单张的 compile 会先校验授权确认；定妆表请求（`compile-sheet` 产出）不含用户照片，生成后用 `CLI attach-sheet` 挂回卡片，不做 frame-check 与 deliver。
1. 先运行 `CLI compile ...`，拿到 `request_path`（绝对路径，下称 R）。
   照片在 compile 之后若被替换或修改，必须重新走授权确认门（consent --photo）并重新 compile；Codex 路径上没有脚本在生成前复查照片。
2. 读取 R，再把字段**逐字**交给内置生图工具：`prompt` 与 R 的 `prompt` 一字不差，`referenced_image_paths` 与 R 的同名字段一致。**不得改写、翻译、增删提示词**（可解析的完整字面量参数按真实字符串逐字比对；未知变量或表达式保持 `unverified`）。S1 实测可用的写法（Codex JS 执行环境，codex-cli 0.161.0）：

   ```js
   const r = await tools.exec_command({cmd: "cat R"}); text(r.output);
   // 下一次调用：把 R 中的 prompt 与 referenced_image_paths 原样填入
   await tools.image_gen__imagegen({prompt: "<R 的 prompt 全文>", referenced_image_paths: ["<R 中的路径>"]})
   ```

3. 只生成一次；失败不重试；平台拒绝时如实转告。同一个 R 只生成一次；重新 compile 不能用于重试被拒内容。内容实质不同的安全替代方案按 dialogue.md“内容审核拒绝后的恢复”核对现有授权，另建请求并保留原拒绝记录；原生开发测试仍按本文相应边界记录，不冒充正式CLI交付。
4. 生成的图片在 `$CODEX_HOME/generated_images/...`，不要移动或重新保存；直接把该路径交给 `CLI frame-check` 和 `CLI deliver`（deliver 会按原字节复制进工作区）。套图第 1 张露脸时的比脸见下文“套图”第 4 步。
5. 先运行 `CLI verify --request R`，会按 R 的路径在 `$CODEX_HOME/sessions` 里自动查找本次会话记录。结果 `unverified` 属于正常限制，告知用户即可。
   默认审计只在可唯一确定的request文件读取窗口内比较全部调用；无法划界、多个请求同批读取或动态参数无法解析时保持unverified，不把其他分镜直接当篡改。显式--log必须是保留完整边界的连续日志窗，不能按匹配prompt筛选。窗口中多次调用不算单次通过。调用审计不是图片输出来源或服务商计费证明。

已知局限：调用形态来自 S1（2026-10-11，codex-cli 0.161.0）实测：会话记录里生图调用为 `tools.image_gen__imagegen({prompt: "…", …})`，并有 `image_gen.generation` 事件与 `revisedPrompt`；`codex exec --json` 的标准输出**不含**生图事件。Codex 升级后需复测；审计为 best-effort。

## 套图（Codex 原生，一套 5 张）

前提：用户明确要求拍摄当前已确定的五张套图；无需固定口令或重复说张数。

1. `CLI compile-shot --set-card S --index 1 [--character C]... --photo P... --workspace WS`，按第 2 步逐字生成一次。
2. 立即登记结果：成功时运行 `CLI set-record --set-card S --workspace WS --index 1 --status generated --image <生成图路径>`；被拒或失败时用 `--status rejected` 或 `--status failed`。
3. 第 1 张不是 generated：账本会把第 2–5 张标为 `cancelled`，`compile-shot` 会拒绝编译它们（`set_cancelled`）。**不得绕过**，如实告诉用户：已登记 1 次提交尝试，其余 4 张没有提交。
4. 第 1 张成功且露脸时，先跑 `CLI likeness-check <第 1 张图> --photo P... --workspace WS`（D34，见 references/face-likeness.md）：`low` 就停下，把第 1 张和本人照片给用户比脸，用户说像再继续（续拍本套），说不像就改方案另起一套；`ok` / `no_face` / `unavailable` 照常继续（`unavailable` 要告诉用户这次没做机器比脸）。之后依次对 index 2、3、4、5 执行 compile-shot → 生成 → set-record，除这次比脸外中途不再询问用户。
5. 这条路径无法在生成前硬拦，只能靠账本与事后审计核对，不得宣称“脚本保证”。

本地生成入口会拒绝同一工作区的重叠操作（workspace_busy），不支持并发生成。新请求另存 reference-hashes.json；旧请求缺少字节记录时需重新编译，不能借旧授权自动重拍。verify/frame-check 记录分别绑定请求与图片；deliver 不接受其他任务或旧格式的 QA 记录。历史 sidecar 不自动升级或改写。

## 单张重拍

用户明确指定某张后保存新的确认卡，用compile编译新请求；需要同组衣装连续性时可加--chain-set <原套图卡>，该首图会校验账本和哈希。首图缺陷或用户换装时先选择是否保留，不能复制错误。Codex继续走原生工具→verify/frame-check/deliver；CLI适配才用generate-exec。新旧图片与审计记录分开保存，不替换历史验收。

## 局部编辑编译

用户明确修改现有图时，先按series-creation的“已认可画面的局部修订”核对底图、原始身份参考与修改范围。保存对应的user_confirmed分镜修订卡；已有素材同意沿用，底图字节尚未登记时，用既有consent命令补录，不重复询问已有授权。

```bash
CLI compile-edit --scene S --image I --instruction '本次明确修改和保留项' --workspace WS
```

I是要修改的那张底图；该入口只引用I，保留修改说明，写标准request.json及reference-hashes.json。分镜卡提供版本关联与确认信息，不将原分镜的整套动作、景别或首图重新注入编辑提示词。只编译，不提交、不改旧图、不替用户验收。用户明确要求零生图编译验证时，在隔离工作区到此停止；编译通过不代表局部编辑效果或像素保持通过。

确有本次生图授权时，先按series-projects将新run_id与本次分镜卡登记为候选、保留原选版，再按上文原样读取请求、调用当前宿主一次、verify／frame-check／deliver及record-verdict；不自动重试。底图变化需按现有同意与参考摘要检查重新核对。调用来源无法核实时保留unverified，未生成或未验收不算complete。

历史手工原生测试保留实际参数与输出，不冒充compile-edit产物，不改旧request后宣称审计pass；未完成实际QA、交付和选版关联前，只记录局部测试的用户反馈。
