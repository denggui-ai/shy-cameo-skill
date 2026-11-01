# 机器比脸（D34，可选）

露脸成图与本人照片的机器相似度，只用来提醒“先给用户比脸”，不判定像不像，也不能当验收。像不像以用户为准。

## 什么时候跑

- Claude Code：`generate-set` 拍完露脸封面（第 1 张）自动跑；分低就返回 `set_paused_likeness`，停在第 1 张。用户说像，再 `--resume` 续拍本套；不像就改方案另起一套，这张不当后几张的连拍参考。结果 unknown 先核对登记再续拍；`unavailable` 照常拍完，交付时说明没比脸。
- Codex 或单张重拍：`CLI likeness-check <图> --photo <本人照片> --workspace <ws>`，返回 `ok` / `low` / `no_face` / `unavailable` 和分数。
- 没装模型、OpenCV 缺这两个接口、或模型哈希不符时一律 `unavailable`，流程照常走，向用户说明“这次没做机器比脸”。

## 模型（不随 skill 分发，用户自行放置）

放到 `<workspace>/cache/face-models/`，或用环境变量 `SHY_CAMEO_FACE_MODELS` 指向目录。来自 OpenCV Model Zoo，脚本按 SHA-256 校验：

| 文件 | 来源 | 许可 | SHA-256 |
|---|---|---|---|
| `yunet.onnx` | opencv_zoo `face_detection_yunet_2023mar.onnx` | MIT | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `sface.onnx` | opencv_zoo `face_recognition_sface_2021dec.onnx` | Apache-2.0 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

下载会访问外部网络，要用户同意后再下；比脸全程在本机，不上传照片。

## 阈值

暂定 0.83（`likeness.LOW_THRESHOLD`）。依据只有 2026-10-25 一位用户的 26 张图：用户判不像或不太像的腰上封面 0.71–0.82，判勉强像的近景 5c 0.86；已定稿的非封面张里也有 0.67–0.77 的。所以只在封面上暂停，不拦其他张。之后每次用户判了像不像，都和分数对一下，再调阈值。
