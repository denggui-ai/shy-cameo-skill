# 安装、升级与卸载

推荐使用 **Codex 自带的 skill-installer**，固定标签 `v1.0.3-rc.1`，目录 `skills/shy-cameo`。版本状态与验证边界以 [对应 Release 说明](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.3-rc.1) 为准；请在该标签发布后安装，发布准备不会自动更新旧安装。

## 安装前

- 运行脚本需要 Python 3.9+，运行环境为 macOS/Linux；当前安装证据来自 macOS arm64 / Codex CLI 0.161.0。Windows 与其他客户端不在本次验证范围。
- 可选组件 OpenCV 使用 `opencv-python-headless>=4.9,<5`；未安装时相关检查转为人工确认，不自动安装依赖。
- 1.0.3-rc.1 默认只带文字与索引，插件安装包小于 5 MB；身形图片与比较页是可选附件，不下载也可正常使用。
- 只选择一种入画安装方式，避免独立技能与插件重复发现。已有同名安装时记录位置和版本，将旧版本备份到技能扫描目录之外。
- 安装不生成图片。开拍另需当前会话支持内置生图、账号登录与额度；照片、同意、账本和成片放在独立私人工作区。

## 推荐安装：skill-installer

在 Codex 新建对话，复制发送：

```text
请使用 skill-installer，从 https://github.com/denggui-ai/shy-cameo-skill
安装 skills/shy-cameo 目录，版本固定为 v1.0.3-rc.1。
只安装，不生图。已有同名安装时先核对位置与版本。
```

安装器写入 `$CODEX_HOME/skills/shy-cameo`，未设置时默认为 `~/.codex/skills/shy-cameo`；实际位置以安装结果为准。已有同名目录时安装器会停止，不要盲目覆盖。安装下载需要联网，不要求把凭据放进项目。

安装完成后新开对话，在技能列表或宿主发现接口核对只有一份启用的 `shy-cameo`，路径指向这次安装。目录存在不等于已被发现。将实际技能路径替换到以下命令做本地检查：

```bash
python3 -B "<skill-dir>/scripts/cli.py" --help
python3 -B "<skill-dir>/scripts/cli.py" validate-library
```

预期帮助正常显示，规则库返回 `{"ok": true, "errors": []}`；两个命令不调用生图。随后在新对话试用：

```text
用 $shy-cameo 和孙悟空在剧组待一天。
先给我看五张分镜，不要生图。
```

预期先给文字方案，缺照片列为后续事项。这是显式试用，不用它证明自动发现通过。

### 升级、回退与卸载

升级前保留旧技能目录和来源版本，确认私人工作区不在安装目录内。将旧版移出扫描目录，再用 skill-installer 安装指定新标签；新开对话，核对路径并重复上述本地检查。回退时移出新版、恢复备份；仍只保留一份生效。历史验证范围见 Release，不将操作步骤当成已实测。

卸载只移除安装结果所指的 `shy-cameo` 目录，核对其中没有私人素材或其他技能后再操作；新开对话确认不再发现。不要删除整个技能目录，独立照片、账本与成片保留。

## 进阶安装（可校验）：插件 ZIP 与本地 marketplace

仅在需要插件管理或手动校验 ZIP 时使用。在 [v1.0.3-rc.1 Release](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.3-rc.1) 下载 `shy-cameo-1.0.3-rc.1.zip` 和同名 `.sha256`。`shy-cameo-source-*.zip` 以及 GitHub 自动生成的 Source code 是开发源码，不是插件安装包。

在下载目录执行：

```bash
shasum -a 256 -c shy-cameo-1.0.3-rc.1.zip.sha256
```

预期 `OK`。摘要从可信发布记录获取；同处下载不能单独证明发布者身份。保留旧包与旧 marketplace 源目录，解包到新目录，按以下结构放置：

```text
market-root/
  .agents/plugins/marketplace.json
  plugins/shy-cameo/
    .codex-plugin/plugin.json
    skills/shy-cameo/SKILL.md
    USER-GUIDE.html
    ...其余包内文件
```

`.agents/plugins/marketplace.json` 内容：

```json
{
  "name": "shy-cameo-local",
  "plugins": [{
    "name": "shy-cameo",
    "source": {"source": "local", "path": "./plugins/shy-cameo"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

`source.path` 相对 `market-root`。将命令中的路径替换为自己选择的绝对路径：

```bash
codex --version
codex plugin marketplace add /absolute/path/to/market-root --json
codex plugin add shy-cameo@shy-cameo-local --json
codex plugin list --marketplace shy-cameo-local --json
```

这些命令登记当前用户的 marketplace/插件并复制到缓存，无需管理员权限；已有同名登记先核对，不盲目覆盖。不同 CLI 版本先看 `--help`。返回版本应为 `1.0.3-rc.1`，并给出 `installedPath`，列表显示 `installed: true`、`enabled: true`。

新开对话核对发现的技能来自该缓存；插件列表有记录不代替技能发现。把 `<skill-dir>` 设为返回的 `installedPath/skills/shy-cameo`，做前面的本地检查。离线隐私与使用说明见 [USER-GUIDE.html](USER-GUIDE.html)。

升级时保留旧 ZIP、摘要与源目录副本，再把 marketplace 的 `plugins/shy-cameo/` 换成校验过的新目录，重复 `codex plugin add`，核对版本、发现路径和本地检查。回退时恢复旧源目录并安装旧版。升级不迁移独立工作区，也不清空未知结果或旧账本。

卸载：

```bash
codex plugin remove shy-cameo@shy-cameo-local --json
codex plugin list --marketplace shy-cameo-local --json
```

新开对话确认该插件技能不再出现。如 marketplace 仅供入画使用，可另执行 `codex plugin marketplace remove shy-cameo-local --json`。解包源目录、备份及私人工作区不会因此自动清理，是否删除另行决定。

## 可选身形图库

**不下载也可正常使用。** 依照本人照片可见部分与文字自述描述身形；需要看图时才按需下载，不把缺图库当错误或开拍前置条件。

在 v1.0.3-rc.1 Release 下载 `shy-cameo-body-reference-20261102.zip` 和 `.sha256`。图库内容版本为 20261102，与本版配套；旧 rc.2 已带图库，无需重复安装。下载后校验，再解压到实际 `<skill-dir>/references/`：

```bash
shasum -a 256 -c shy-cameo-body-reference-20261102.zip.sha256
unzip shy-cameo-body-reference-20261102.zip -d "<skill-dir>/references"
```

预期出现 `body-reference/compare.html` 和 `body-reference/images/`；两份索引原本已在默认安装中。已有同名图片时先备份并核对版本，不盲目覆盖。插件升级后路径可能改变，按新路径手动放回匹配附件；没有下载器、自动缓存或安装 hooks。解压前后文件摘要可与附件白名单核对，图库只作沟通示例。

## 其他宿主

Claude Code 路径保持实验性：将技能目录复制到 `~/.claude/skills/shy-cameo`，重启后做相同本地检查；实际生成经已登录的 Codex CLI 转发。它不属于推荐安装主路径，也不由本轮文档整理新增兼容性保证。

## 遇到问题

通过项目 [Issues](https://github.com/denggui-ai/shy-cameo-skill/issues/new/choose) 反馈，只提供系统、Codex/技能版本、安装方式、CLI 的 `status` 与脱敏复现步骤；不要上传照片、consent、账号信息或完整私人日志。安全或隐私问题按仓库 SECURITY.md 联系。旧版本安装证据归入 CHANGELOG 与开发验证文档，本指南只保留当前操作路径。
