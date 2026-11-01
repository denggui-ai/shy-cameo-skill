# shy-cameo · 入画 — AI Story Portraits Skill

> Public test release: **[1.0.2-rc.1](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.2-rc.1)**. Clean source and a Codex plugin package are available. The feature scope is frozen. Approved examples do not establish reliability across all modes. See [validation scope](release/VALIDATION.md).

[简体中文](README.md) · [Installation guide (Chinese)](release/INSTALL.md) · [Capabilities (Chinese)](release/CAPABILITIES.md)

**Step into a classic story with your own photo.** From one clear front-facing photo of yourself or a consenting adult, shy-cameo makes a five-image set of 3:4 AI story portraits. You are the lead; the story character is too shy to show its face and keeps you company only from behind, with its hands, and as a shadow.

## What it can do

"Stable" means a full five-image set was actually shot under the current rules and approved by the author. "Experimental" means the feature exists but results are not guaranteed. The full list with example phrasing is in the [capability list](release/CAPABILITIES.md) (Chinese).

| Class | What you can ask for | Tier |
|---|---|---|
| 1 Be with a character | A day on set, everyday life together, step into their world (e.g. "a day on set with Sun Wukong", "find Sun Wukong at Flower-Fruit Mountain") | Stable |
| 1 Be with a character | Travel with the character as your guide | Experimental |
| 2 Become someone | Chinese opera costume, foreign characters in opera costume, try on a character's outfit | Experimental |
| 3 Enter a story | A scene from a film (e.g. the 1902 silent film A Trip to the Moon) | Stable |
| 3 Enter a story | A chapter of an original novel, a genre film, an adventure with an original character (e.g. Atan, a fox innkeeper) | Experimental |
| 4 Travel on your own | One city or several countries | Stable |
| 5 Everyday life with a pet | A small everyday moment with your pet | Experimental |

You can also choose the look (photographic is stable; turning into anime is experimental), the outfit, and how many sets (one set, or continuing, is stable), or bring your pet along (experimental). After a set you can ask for a caption draft and a local gallery page (experimental). You see the plan first and decide whether to shoot; looking at the plan uses no image-generation quota.

## AI virtual-model examples

Real-person showcase assets have been removed from this historical version. [Browse the current AI virtual-model gallery](https://github.com/denggui-ai/shy-cameo-skill/blob/main/release/CASES.md).

## Install

Follow the [installation guide](release/INSTALL.md) (Chinese) and select the fixed tag `v1.0.2-rc.1`. Plugin ZIP and checksums are in [Releases](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.2-rc.1). **Codex has historical validation** (macOS arm64 / Codex CLI 0.161.0); **Claude Code is experimental**. Python 3.9+ is required; actually generating images also needs a Codex session with built-in image generation, a signed-in account and quota.

After installing, open a new conversation, upload a selfie and say, for example:

```text
Use $shy-cameo to spend a day on set with Sun Wukong. Show me the plan first, do not generate images.
```

Confirm the plan, then say to shoot it with no retries on failure. One set is five generation calls, and failures may still use quota.

## Features and risks

- Faces drift: not every shot will look like you, and head turns, big movements and full-body wide shots are more likely to go off.
- Body guidance uses visible photo evidence, your description and explicit local adjustments. A headshot plus a description is supported; three full-body views are not required. The optional synthetic gallery helps communicate preferences, but precise body or bust control and consistency across outfits, side views and back views remain unverified.
- Hands are sometimes drawn wrongly; check each image.
- Your photo is sent to the image-generation service and handled under that service's rules. This project does not collect photos and is not an offline tool.
- Items marked experimental come with no guarantee of results.

## Your responsibility

- You are responsible for the photos you upload and the content you generate; upload only photos of yourself or of a consenting adult.
- If the person in the photo is not you, tell them what you will do and get their separate consent first.
- Whether a generated image can be used commercially depends on the image service's terms and the rights in the characters involved. Commercial use requires you to obtain authorization yourself.

## AI-generated content

The images are AI-generated and do not represent, and are not affiliated with, any rights holder of any work.

## Not legal advice

Statements about rights in this document and this repository are not legal advice.

## Complaints and feedback

For copyright or likeness complaints, and for security and privacy reports, see [SECURITY.md](SECURITY.md). Other questions can go to [Issues](https://github.com/denggui-ai/shy-cameo-skill/issues); do not attach photos or personal information to a public issue.

[Validation scope](release/VALIDATION.md) · [Development](release/DEVELOPMENT.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## License

[MIT](LICENSE). The software license does not grant other uses of anyone's likeness. Not affiliated with Cameo. Formerly named classic-coshoot.
