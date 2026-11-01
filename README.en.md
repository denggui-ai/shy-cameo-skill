# shy-cameo · 入画

**Step into a classic story with your own photo.**

Use this Codex skill to turn one clear front-facing photo into **five 3:4 AI story portraits**. You are the lead; your fictional companion is a little shy and appears through back views, hands and shadows. Review the storyboard before deciding to generate.

[Get started](#get-started-in-three-steps) · [More examples](release/CASES.md) · [Installation guide](release/INSTALL.md) · [简体中文](README.md)

> Public test release **[v1.0.2-rc.1](https://github.com/denggui-ai/shy-cameo-skill/releases/tag/v1.0.2-rc.1)** · Source and a Codex plugin package are available. These are actual generated examples; results will vary.

## AI virtual-model examples

Real-person showcase assets have been removed from this historical version. [Browse the current AI virtual-model gallery](https://github.com/denggui-ai/shy-cameo-skill/blob/main/release/CASES.md).

## Get started in three steps

You need **Codex and Python 3.9+**. Generating pictures also requires a Codex session with built-in image generation, a signed-in account and available quota. Installation does not generate images.

### 1. Install a fixed version

Open a Codex conversation and send:

```text
Use skill-installer to install skills/shy-cameo from
https://github.com/denggui-ai/shy-cameo-skill at tag v1.0.2-rc.1.
Install only; do not generate images. If shy-cameo is already installed,
check its location and version first.
```

**Start a new conversation after installation.** See the [installation guide](release/INSTALL.md) for plugin ZIP installation, upgrades and removal. Codex has historical validation on macOS; Claude Code remains experimental. See the [validation scope](release/VALIDATION.md) for tested environments and gaps. These detailed guides are in Chinese.

### 2. Preview a storyboard

You can try the plan without uploading a photo yet:

```text
Use $shy-cameo to spend a day on set with Sun Wukong.
Show me a five-shot storyboard first. Do not generate images.
```

You will get a plan covering each shot's scene, outfit and action. Change the theme, clothes or story before shooting. **This step makes no image-generation calls and uses no image-generation quota.**

### 3. Confirm and generate

Upload a clear front-facing photo of yourself or a consenting adult. Once you approve the plan, send:

```text
Generate this set. Do not retry failed calls.
```

A five-image set uses five generation calls; failures may still use quota. Check the face, hands and body in each image. Results depend on the image model.

## Try another story

| What you want | What to ask for |
|---|---|
| Spend time with a character | “Find Sun Wukong at Flower-Fruit Mountain” / “Spend a day on set with Sun Wukong” |
| Enter a film | “Step into the 1902 silent film A Trip to the Moon” |
| Travel on your own | “Make a portrait set of a walk through Paris” |
| Try a costume (experimental) | “Wear a Chinese opera huadan costume for a backstage set” |
| Everyday life with a pet (experimental) | “Spend a quiet afternoon with my cat” |

You can also continue with another set, try visual styles or create an original character. Validation varies by mode; see the [capability list](release/CAPABILITIES.md) (Chinese). Its “stable” label means an author-approved complete example exists, not that results are guaranteed.

## Before you use it

- **Likeness has limits.** Head turns, large movements and full-body wide shots can cause face drift. Hands can be drawn incorrectly.
- **Body guidance follows available evidence.** Use a body photo, a headshot with your description, or explicit local adjustment requests. Three full-body views are not required. The optional gallery is a communication aid; precise body or bust control and consistency across outfits, side views and back views remain unverified.
- **Photos are sent to the image service.** This project does not collect photos and is not fully offline. Upload only photos of yourself or consenting adults. Explain the intended use and obtain separate consent before using someone else's photo.
- **Publication and commercial use involve rights.** You are responsible for uploaded and generated content. Commercial use depends on the image service's terms and the rights in the characters involved; obtain the necessary authorization yourself.

## Feedback and contributions

For questions or suggestions, open an [issue](https://github.com/denggui-ai/shy-cameo-skill/issues) with your environment and steps to reproduce. **Do not post private photos or personal information.** For copyright, likeness, security or privacy concerns, follow [SECURITY.md](SECURITY.md).

[Validation scope](release/VALIDATION.md) · [Development](release/DEVELOPMENT.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

The [MIT license](LICENSE) covers the software, not other uses of anyone's likeness. Images are AI-generated. This project is not affiliated with any featured work's rights holders or with Cameo. Rights statements are not legal advice. Formerly named classic-coshoot.
