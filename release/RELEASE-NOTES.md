# v1.0.3-rc.1

入画预发布版，固定安装标签为 `v1.0.3-rc.1`。

## 新增

- 修复工作区迁移后的路径处理与调用审计问题，保留旧记录及未知结果的核对边界。
- 重组技能主流程，提供未确认草稿的非阻断构图建议检查，精简故事写真与角色海报之间的触发边界。
- 默认安装只保留身形文字与索引；31 个图片文件和比较页改为可选图库附件。未下载时继续使用照片可见信息与文字自述，不报错、不阻断。
- 统一中英 README、安装指南、问题反馈入口与版本说明。

## 安装

推荐使用 Codex 自带的 `skill-installer`，从 `denggui-ai/shy-cameo-skill` 安装 `skills/shy-cameo`，固定标签 **v1.0.3-rc.1**。已有安装先保留旧版，安装后新开对话；步骤见[安装指南](https://github.com/denggui-ai/shy-cameo-skill/blob/v1.0.3-rc.1/release/INSTALL.md)。

需要插件管理时，下载 `shy-cameo-1.0.3-rc.1.zip` 和同名 `.sha256`，按安装指南配置本地 marketplace。只选择一种安装方式，避免重复发现。

图库按需下载 `shy-cameo-body-reference-20261102.zip` 和同名 `.sha256`，校验后解压到实际技能目录的 `references/`。默认安装小于 5 MB，不下载图库也能正常使用。GitHub 自动提供的 Source code 是开发源码，不是插件安装包。

## 已知限制

- 发布前同一技能正文在 macOS / Codex CLI 0.161.0、日常 `gpt-6-astra / max` 配置中通过六个全新会话：M01 三次均加载、M02 三次均不加载；临时安装已卸载，日常 rc.2 已恢复。结论只覆盖这两条中文题面，见[简测记录](https://github.com/denggui-ai/shy-cameo-skill/blob/v1.0.3-rc.1/release/dev/AUTO-DISCOVERY.md)。其他题面、语言、新设备和桌面点击未由此验证。
- 自动发现通过不等于完整首用流程或成片质量通过。既有 AI 模特案例及一次袖口局部编辑的用户接受记录，不证明真人身份、精确身形、跨衣装一致性或编辑区域外像素保持。
- 本轮发布准备未新增真实生图。原生图像工具提交前仍没有程序硬拦，轨迹不完整时调用审计仍可能无法核验；其他宿主仍属实验范围。

## 校验

四个发布附件为两个 ZIP 及各自的 SHA-256 文件。在下载目录运行，两个结果均应为 `OK`：

```bash
shasum -a 256 -c shy-cameo-1.0.3-rc.1.zip.sha256
shasum -a 256 -c shy-cameo-body-reference-20261102.zip.sha256
```

| ZIP | 字节 | SHA-256 |
| --- | ---: | --- |
| `shy-cameo-1.0.3-rc.1.zip` | 181,844 | `867be6e4f7909fbd3f2484cac16932a417239618ba3c4cf823bbaef8c0bdecdc` |
| `shy-cameo-body-reference-20261102.zip` | 50,639,044 | `fe34660d35e186f64c320c75428663f2bb1208aa0a9eb3e59f0aa96f56905cd9` |

插件解压后为 428,877 字节，也小于 5 MB。摘要应来自可信发布记录；本版不替换旧标签或旧附件。

发布者重新打包图库时，在保有原始图库的开发仓库根目录运行，输出目录须尚不存在：

```bash
python3 -B scripts/build_body_reference_bundle.py --assets build/body-reference-assets-20261102/body-reference --allowlist release/body-reference-allowlist.json --output build/body-reference-v1.0.3-rc.1
```

脚本只读取本地白名单文件，逐项核对大小与摘要后生成 ZIP 和 `.sha256`；不下载、不安装、不生图。发布时由作者手动上传四个附件。
