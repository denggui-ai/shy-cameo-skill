# 入画 · shy-cameo

> 此源码包为 **1.0.2-rc.2 本地更新版**，新增已实测的 `compile-edit`。安装本版请使用随附的插件 ZIP，见[安装指南](release/INSTALL.md)。下文 GitHub 的 v1.0.2-rc.1 是上一公开版；本次未发布新的远端版本。

**用你的照片，走进想经历的故事。**

入画是一个 **Codex AI 故事写真技能（skill）**：从一张清楚的正脸照开始，策划并生成一套五张 3:4 竖图。和喜欢的角色同框、换上戏服、走进电影、独自旅行，或记录与宠物相处的日常。你是主角；陪同角色有点害羞，用背影、手和影子入镜。

[开始使用](#三步开始) · [完整案例集](release/CASES.md) · [5 类玩法](release/CAPABILITIES.md) · [安装指南](release/INSTALL.md) · [English](README.en.md)

> 公开测试版 **[v1.0.2-rc.1](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.2-rc.1)** · 先看分镜，再决定开拍；拍完可以继续下一套，也可以只改某一张并保留旧版。

## 选一个故事，看看效果

以下为已获认可的 **AI 虚拟成年模特**案例，点击封面看完整五张。画面展示可达到的效果，不保证每次一致；AI 模特案例也不等于真人锁脸或精确身材控制验证。

<p>
<a href="release/cases/virtual-fox-inn.md"><img src="assets/showcase/virtual-fox-inn/01.jpg" width="150" alt="狐狸客栈的傍晚" title="狐狸客栈的傍晚"></a>
<a href="release/cases/virtual-wukong-cave.md"><img src="assets/showcase/virtual-wukong-cave/01.jpg" width="150" alt="跟孙悟空走进水帘洞" title="跟孙悟空走进水帘洞"></a>
<a href="release/cases/virtual-yuji-opera.md"><img src="assets/showcase/virtual-yuji-opera/01.jpg" width="150" alt="虞姬：从后台到舞台" title="虞姬：从后台到舞台"></a>
<a href="release/cases/virtual-mulan.md"><img src="assets/showcase/virtual-mulan/01.jpg" width="150" alt="木兰：披甲与归来" title="木兰：披甲与归来"></a>
</p>

<p>
<a href="release/cases/virtual-wuxia.md"><img src="assets/showcase/virtual-wuxia/01.jpg" width="150" alt="栈道上的武侠交锋" title="栈道上的武侠交锋"></a>
<a href="release/cases/virtual-paper-crane.md"><img src="assets/showcase/virtual-paper-crane/01.jpg" width="150" alt="纸鸢的动画冒险" title="纸鸢的动画冒险"></a>
<a href="release/cases/virtual-cappadocia.md"><img src="assets/showcase/virtual-cappadocia/01.jpg" width="150" alt="卡帕多奇亚的夜色" title="卡帕多奇亚的夜色"></a>
<a href="release/cases/virtual-cat-daily.md"><img src="assets/showcase/virtual-cat-daily/01.jpg" width="150" alt="和猫的安静夜晚" title="和猫的安静夜晚"></a>
</p>

[狐狸客栈](release/cases/virtual-fox-inn.md) · [水帘洞](release/cases/virtual-wukong-cave.md) · [虞姬](release/cases/virtual-yuji-opera.md) · [木兰](release/cases/virtual-mulan.md)<br>
[武侠交锋](release/cases/virtual-wuxia.md) · [动画冒险](release/cases/virtual-paper-crane.md) · [夜景旅行](release/cases/virtual-cappadocia.md) · [和猫过日常](release/cases/virtual-cat-daily.md)

**[查看 11 套 AI 模特案例、55 张成片 →](release/CASES.md)** 另有雅典娜戏曲扮相、《画壁》和《月球旅行记》。

## 三步开始

需要 **Codex + Python 3.9+**。真正开拍还需要当前 Codex 会话支持内置生图、已登录账号和可用额度。安装本身不生成图片。

### 1. 安装固定版本

在 Codex 新建对话，复制发送：

```text
请使用 skill-installer，从 https://github.com/denggui-ai/shy-cameo-skill
安装 skills/shy-cameo 目录，版本固定为 v1.0.2-rc.1。
只安装，不生图。已有同名安装时先核对位置与版本。
```

安装完成后**新开对话**。当前发布版已在 macOS / Codex CLI 0.161.0 的隔离环境通过直接安装、插件 ZIP 安装、新进程发现及一次首次分镜试用。插件安装步骤见[安装指南](release/INSTALL.md)，具体范围见[验证记录](release/VALIDATION.md)。

### 2. 先试一套分镜

可以先不上传照片，直接发送：

```text
用 $shy-cameo 和孙悟空在剧组待一天。
先给我看五张分镜，不要生图。
```

你会看到五张照片的场景、衣装和动作方案。可以改主题、换衣服或调整情节。**这一步不调用生图，也不消耗生图额度。**

### 3. 确认后再拍

上传一张本人或已获同意的成年人的清楚正脸照，确认分镜后发送：

```text
按这套拍，失败不重试。
```

一套最多五次生图调用，失败也可能消耗额度。逐张检查人脸、手和身形。想调整时可以说“只改第 3 张的动作”，或继续拍下一个系列；旧版保留。局部修改仍可能影响其他细节。

## 5 类玩法，13 种方向

| 想拍什么 | 可以这样说 | 看案例 |
|---|---|---|
| 和角色同框 | “和狐狸掌柜过一天”／“去花果山找孙悟空” | [狐狸客栈](release/cases/virtual-fox-inn.md)、[水帘洞](release/cases/virtual-wukong-cave.md) |
| 扮成一个人 | “穿虞姬的戏曲扮相”／“试穿木兰主题盔甲” | [虞姬](release/cases/virtual-yuji-opera.md)、[木兰](release/cases/virtual-mulan.md) |
| 走进一个故事 | “走进《画壁》”／“拍一部武侠片” | [画壁](release/cases/virtual-painted-wall.md)、[武侠](release/cases/virtual-wuxia.md) |
| 自己去旅行 | “拍一套卡帕多奇亚夜景旅行写真” | [夜景旅行](release/cases/virtual-cappadocia.md) |
| 和宠物过日常 | “和我的猫度过一个安静的夜晚” | [猫的陪伴](release/cases/virtual-cat-daily.md) |

支持摄影感、全动画和摄影人物＋动画环境，也可调整衣装、光线、机位与动作。可用玩法、已有案例和仍需试验的范围分别列在[能力清单](release/CAPABILITIES.md)。

## 使用前了解这些

- **相似度有局限。** 转头、大动作和全身远景可能让人脸漂移，手也可能画错。
- **身形按已有依据描述。** 支持身体照片、只有头像时的自述，以及明确的局部调整要求；不强制提供全身三视图。可选图库只是沟通示例，精准身材／胸型控制及换装、侧身、背影的一致性尚未验证。
- **照片会交给生图服务处理。** 本项目不收集照片，也不是全程离线工具。只上传本人或已获同意的成年人的照片；使用他人照片前，应说明用途并取得对方单独同意。
- **公开与商用需留意权利。** 你对上传和生成的内容负责；商用取决于生图服务条款及所涉角色的权利，须自行取得相应授权。

## 反馈与参与

使用问题或建议请到 [Issues](https://github.com/denggui-ai/shy-cameo-skill/issues)，附上使用环境和复现步骤，**不要公开上传私人照片或个人信息**。版权、肖像权、安全与隐私问题请按 [SECURITY.md](SECURITY.md) 联系。

[逐项验证记录](release/VERIFICATION-MATRIX.md) · [补测计划与张数](release/NEXT-TESTS.md) · [历史验证范围](release/VALIDATION.md) · [开发与复现](release/DEVELOPMENT.md) · [变更记录](CHANGELOG.md) · [贡献说明](CONTRIBUTING.md)

[MIT 许可](LICENSE) 适用于软件，不包含肖像的其他使用授权。成片由 AI 生成，本项目与作品权利方及 Cameo 无关联。权利说明不是法律意见。本项目原名 classic-coshoot。
