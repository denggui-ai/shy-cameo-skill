# 安装、升级与卸载

> 公开测试版 **[1.0.2-rc.1](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.2-rc.1)**，仓库为 `denggui-ai/shy-cameo-skill`，技能名仍为 `shy-cameo`。已有本地安装使用记录；干净解包启动已验证，新机器安装／发现及本版本升级回退尚未复验。

源码仓库提供首页、英文说明和 `release/VALIDATION.md`；插件包内可查看随包的 `USER-GUIDE.html`。

## 选择安装方式

| 方式 | 适合谁 | 安装后的名称 |
|---|---|---|
| A：直接安装 skill（推荐） | 想在 Codex 中快速开始 | `shy-cameo`，显式调用 `$shy-cameo` |
| B：本地插件安装 | 需要通过 CLI 管理插件生命周期 | 插件 `shy-cameo@shy-cameo-local`；发现接口名称 `shy-cameo:shy-cameo` |

选择一种即可。不要同时装两份；切换方式前先确认旧安装的位置并卸载，避免同名技能重复发现。两条路径使用同一版本技能，安装本身不生成图片。

## 安装前检查

- **Codex 已验证**（macOS arm64 / Codex CLI 0.161.0）；**Claude Code 实验性**（见下节）。Windows、桌面界面点击和其他客户端未验证；进程锁依赖 macOS/Linux。
- 运行脚本需要 Python 3.9+ 标准库。OpenCV 4.x 和 Pillow 为可选组件，不自动安装。
- 包内含可选的合成身形沟通示例，解包约 54 MiB；保留下载包、解包与安装缓存时建议至少预留 200 MiB。安装耗时取决于下载及宿主，不含后续生图。
- 真正生图另需当前宿主会话支持内置图像生成、登录账号与可用额度；安装成功不代表会话具备生图能力。
- 照片、同意记录、账本和成片放在仓库外私人工作区。升级或卸载技能不等于删除这些数据。

## 在 Claude Code 里安装（实验性）

1. 把 `skills/shy-cameo` 复制到 `~/.claude/skills/shy-cameo`（或项目内 `.claude/skills/shy-cameo`）。
2. 重启 Claude Code。
3. 跑自检（不生图）：`python3 ~/.claude/skills/shy-cameo/scripts/cli.py preflight --workspace <空目录>`。
4. Claude Code 里实际生图仍经 Codex CLI（见 `SKILL.md`），所以要先装好并登录 Codex。

2026-10-26 在干净临时项目里验证过：复制后 preflight 通过，Claude Code 能列出 `shy-cameo`；没有真实生图，仍标“实验性”。

## A：直接安装 skill（推荐）

从 [https://github.com/denggui-ai/shy-cameo-skill](https://github.com/denggui-ai/shy-cameo-skill) 安装，固定使用版本标签 `v1.0.2-rc.1` 和目录 `skills/shy-cameo`。

在 Codex 新建对话，发送：

```text
请使用 skill-installer，从 https://github.com/denggui-ai/shy-cameo-skill 安装 skills/shy-cameo 目录，版本固定为 v1.0.2-rc.1。只安装，不生图。已有同名安装时先核对位置与版本。
```

安装器写入当前用户的 Codex 技能目录。已有同名目录时先核对位置与版本，不直接覆盖；安装结果应给出实际路径。

### 确认安装成功

1. 安装后新开对话，检查技能列表或宿主发现接口中有启用的 `shy-cameo`，路径指向本次安装。
2. 将安装结果中的路径记为 `<skill-dir>`，在终端把占位符换为实际绝对路径，执行：

```bash
python3 -B "<skill-dir>/scripts/cli.py" --help
python3 -B "<skill-dir>/scripts/cli.py" validate-library
```

预期显示帮助，规则库返回 `{"ok": true, "errors": []}`。不调用图像服务。之后可按源码仓库首页的示例准备分镜。

历史验证：2026-10-16 在 macOS / Codex CLI 0.161.0 的隔离目录，使用系统 skill-installer 安装过旧版 v1.0.1，并检查文件、发现接口、CLI 帮助和规则库。该记录不代表新仓库或新版本已经通过同样检查；桌面点击及其他系统未验证。

### 升级与卸载

升级前记录实际安装路径并备份旧技能目录，确认私人工作区独立保存。将旧安装移出技能发现目录，再用上面的请求指定目标版本安装；新开会话检查只发现一份技能，并重新运行零额度检查。该直接安装路径的跨版本升级与回退尚未实测，不等同于下面已验证的插件刷新流程。

卸载时只移除安装结果所指的 `shy-cameo` 技能目录；先核实目录内没有私人素材或其他技能，再在文件管理器中操作。新开会话确认不再发现该技能。不要删除整个 Codex 技能目录。该直接安装路径的卸载尚未单独实测。

## B：本地插件安装

在 [v1.0.2-rc.1 Releases](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.2-rc.1) 下载 `shy-cameo-1.0.2-rc.1.zip` 和 `shy-cameo-1.0.2-rc.1.zip.sha256`。`shy-cameo-source-1.0.2-rc.1.zip` 是开发源码，不是插件包。在下载目录执行：

```bash
shasum -a 256 -c shy-cameo-1.0.2-rc.1.zip.sha256
```

预期 `OK`。摘要应来自可信发布记录；同处下载不能单独证明发布者身份。确认插件包的版本与所需版本一致。

历史验证：2026-10-16 曾用旧版 v1.0.1 安装包在 macOS arm64 / Codex CLI 0.161.0 的隔离配置验证新装、发现、升级和卸载；该记录不证明新包已经通过相同检查，也不代表桌面点击、其他平台、模型自动触发或生图通过。

### 安装插件


先校验 ZIP，解包到自己选择的本地目录，按下面布局放置。`market-root` 是目录示例名，后续命令要换成它的绝对路径。不要将真人照片放入此目录。

```text
market-root/
  .agents/plugins/marketplace.json
  plugins/shy-cameo/
    .codex-plugin/plugin.json
    skills/shy-cameo/SKILL.md
    USER-GUIDE.html
    ...其余包内文件
```

新建 `.agents/plugins/marketplace.json`，内容为：

```json
{
  "name": "shy-cameo-local",
  "plugins": [
    {
      "name": "shy-cameo",
      "source": {"source": "local", "path": "./plugins/shy-cameo"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
```

`source.path` 相对 `market-root`，不是相对 `.agents/plugins/`。检查当前 CLI 版本后，执行：

```bash
codex --version
codex plugin marketplace add /absolute/path/to/market-root --json
codex plugin add shy-cameo@shy-cameo-local --json
codex plugin list --marketplace shy-cameo-local --json
```

这会在当前用户的 Codex 配置中登记本地 marketplace 和插件，并复制到插件缓存；不需要管理员权限，也不安装依赖。先检查同名 marketplace/插件；已有安装应备份原目录和包，不盲目覆盖。旧版实测是在空配置目录完成的。

安装结果应返回与所选插件包一致的版本和 `installedPath`，列表应显示 `installed: true`、`enabled: true`。实际安装位置以返回值为准，不猜缓存路径。安装后新开会话，再确认技能发现；列表里有插件还不是技能发现的证据。

### 确认发现和零额度试用

旧版隔离测试通过独立新进程的 `skills/list` 确认发现了 `shy-cameo:shy-cameo`；安装新包后仍需对当前安装结果自行核对。

普通使用者在新会话的技能列表中检查“入画 shy-cameo”；若当前客户端没有显示技能列表，以宿主自身的发现接口或诊断为准，不把目录存在当作发现成功。本轮未做桌面界面点击验证。

在安装结果 `installedPath` 对应的目录中，执行：

```bash
python3 -B skills/shy-cameo/scripts/cli.py --help
python3 -B skills/shy-cameo/scripts/cli.py validate-library
```

第二条预期 `{"ok": true, "errors": []}`。这两项检查不调用图像服务；不要用生图来测试是否安装成功。

### 升级

保留旧 ZIP、摘要及源目录副本。把 marketplace 指向的 `plugins/shy-cameo/` 更新为校验过的新版本，然后再次执行同一条 `codex plugin add shy-cameo@shy-cameo-local --json`。核对返回版本、`installedPath`，新开会话确认发现来自新版缓存，再做零额度检查。

历史验证用保留的 v1.0.0 原包安装，再升级到 v1.0.1 实际发行包。新进程只发现一份新版插件技能，安装内容与发行包逐文件相等；CLI 与规则库检查通过。本证据不证明任意未来版本的数据迁移。同版本覆盖、Git marketplace 自动升级与回退未实测。

私人照片、授权与账本放在独立工作区，升级不迁移这些数据。旧四张卡/账本仍需原有的五张迁移与重新确认规则。

### 卸载

```bash
codex plugin remove shy-cameo@shy-cameo-local --json
codex plugin list --marketplace shy-cameo-local --json
```

应无此插件的 installed 记录；新开会话确认该插件技能不再出现。v1.0.1 历史验证同时确认该插件的缓存目录被删除，合成的独立工作区文件内容保持不变。

若此 marketplace 只供本插件使用，可另执行：

```bash
codex plugin marketplace remove shy-cameo-local --json
```

这撤除 marketplace 登记，不代替删除你解包的源目录、照片或生成结果。源目录和独立工作区可继续保留；是否清理由用户单独决定。不要使用全盘清理命令。

依据：[OpenAI 本地插件说明](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)、[技能发现接口](https://learn.chatgpt.com/docs/app-server#skills)。本机 CLI 的命令与返回值是本轮实测依据；不同版本须先核对 `--help`。
