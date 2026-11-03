# 开发与验证文档

[项目首页](../../README.md) · [安装](../INSTALL.md) · [版本说明](../RELEASE-NOTES.md) · [能力与案例](../CAPABILITIES.md)

面向使用者的安装、能力和案例留在 `release/`；开发过程、验证范围及历史复核集中在本目录。带日期的旧状态仅说明当时情况，不覆盖当前计划。

- [开发与复现](DEVELOPMENT.md)：当前决定、运行规则及历史流水。
- [逐项验证](VERIFICATION-MATRIX.md)、[历史验证范围](VALIDATION.md)、[补测计划](NEXT-TESTS.md)：区分程序、模型行为、视觉与用户验收证据。
- [M01/M02 自动发现手测](AUTO-DISCOVERY.md)：两条中文题面各3次，M01三次加载、M02三次不加载；范围与环境见记录。
- [巴黎问题复核](PARIS-LOCATION-REVIEW.md)：取景与人体结构问题记录。

私有开发源还保留本地案例检查、摄影复核、动画验证、旧排期和能力历史，未增加公开导出范围。原始证据与冻结快照仍在开发源，原始照片、私人日志和 `evidence/` 不因移动文档而进入公开源码或安装包；公开展示只按独立白名单包含获准的生成图。历史记录中的旧路径可对照 Git 历史或本目录的同名文件查阅。

在仓库根目录准备开发环境并运行检查：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/ -q -p no:cacheprovider
.venv/bin/python -B skills/shy-cameo/scripts/cli.py validate-library
```

测试使用合成素材和 fake 后端。具体提交按改动范围选取必要检查，不把程序通过视为自动发现、真实生图或成片质量通过。
