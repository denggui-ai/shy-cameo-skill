# Capabilities

[Home](../README.en.md) · [Examples](CASES.en.md) · [Verification matrix (中文)](dev/VERIFICATION-MATRIX.md) · [Test plan (中文)](dev/NEXT-TESTS.md) · [简体中文](CAPABILITIES.md)

Tell Codex who you want to meet, where you want to go, what you want to wear or what story you want to experience. There are **five categories and thirteen directions**.

| Category | Direction | Example / evidence |
|---|---|---|
| Character companionship | A day on set | Earlier real-person sets were accepted; the third virtual-model set was accepted on 2026-11-02. Scoped text-only storyboard preparation passed |
| Character companionship | Everyday life together | [Fox Inn](cases/virtual-fox-inn.md): virtual adult in an illustrated world; real-person sets also exist |
| Character companionship | Enter their world | [Sun Wukong](cases/virtual-wukong-cave.md): accepted virtual and earlier real-person sets |
| Character companionship | A character as your travel guide | Experimental; the earlier virtual-model set was not accepted; the five-image remake addressing cinematic quality, an affectionate cat and styling was accepted, limited to that combination |
| Costume portraits | Chinese opera | [Yuji](cases/virtual-yuji-opera.md): accepted virtual-model example; real-person workflow remains experimental |
| Costume portraits | Cross-cultural opera styling | [Athena](cases/virtual-athena-opera.md): accepted virtual-model example; real-person workflow remains experimental |
| Costume portraits | Character-inspired clothing | [Mulan](cases/virtual-mulan.md): accepted virtual-model example; real-person workflow remains experimental |
| Enter a story | A literary episode | [The Painted Wall](cases/virtual-painted-wall.md): accepted virtual-model example; real-person workflow remains experimental |
| Enter a story | Genre cinema | [Wuxia](cases/virtual-wuxia.md): accepted virtual-model example; real-person workflow remains experimental |
| Enter a story | A film setting | [A Trip to the Moon](cases/virtual-moon-film.md): revised virtual set substantially accepted; earlier real-person set exists |
| Enter a story | An original character adventure | [Zhiyuan](cases/virtual-paper-crane.md): accepted animated example; real-person workflow remains experimental |
| Travel on your own | One city or several countries | [Cappadocia](cases/virtual-cappadocia.md): virtual set broadly accepted; earlier real-person sets exist |
| Everyday life with a pet | Familiar moments and interaction | [A quiet evening with a cat](cases/virtual-cat-daily.md): third virtual set accepted overall, with a book-detail issue; real-person workflow remains experimental |

“Existing accepted real-person set” means a complete five-image set was reviewed and accepted by its subject. Older documents call this “stable”; it is not a guarantee. The eleven newly published virtual-model sets broaden the examples, without promoting the real-person validation tiers. These POCs used virtual-subject wording adaptations and do not establish an automated real-person CLI run.

## What you can adjust

- Photographic, fully animated or photographic-subject/animated-world styles; lighting, framing, camera angle and actions.
- Clothing, accessories and materials, with choices informed by your photo and the scene.
- A five-shot story, another series, or selected multiple series. “Shoot all” remains experimental and covers only the series you selected.
- One shot or a local detail, while retaining the previous version. Local edits may alter other details.
- A pet in a travel or character set (experimental), using a clear photo of your own pet.
- Optional posting text and a local gallery (experimental); the skill does not publish for you.

## What to prepare

Start the storyboard without a photo if you wish. Before generating, provide one clear front-facing photo of yourself or a consenting adult. Explain the intended use and obtain separate consent for another adult's photo. For a pet, add a clear photo of your own animal. These references are sent to the image service through your account.

Body guidance can use visible evidence in a body photo, your description when only a headshot is available, and explicit local adjustment requests. Three full-body views are not required. The optional synthetic gallery is a communication aid; precise body or bust control and consistency across clothes, side views and back views remain unverified.

## What to expect

Each set contains five vertical 3:4 images, with changing actions, framing and story moments. Usually one or two show your face clearly; the rest use back views, hands, over-the-shoulder views, silhouettes or distance. Fictional companions remain shy and do not show their faces. Human identity, hands, costumes, props and character recognition still need visual review.

At most five generation calls are submitted for a set. Submitted failures may use quota; a failed first image cancels the remaining shots, and retries are not automatic. Originals are retained without re-encoding; optional visible AI labels are separate copies. The public gallery uses resized web copies.

The skill does not handle minor subjects, composites with real celebrities, multiple real people in one frame, landscape output, automatic beauty/slimming edits, on-image text, automatic posting, or a full asset-management center. Reference atmosphere images are interpreted in words; precise light/color transfer is not established.

Current release installation and discovery passed for both direct-skill and plugin-ZIP paths on macOS / Codex CLI 0.161.0 in isolated configurations. One explicit first-use storyboard request passed with image generation disabled. Desktop clicks, implicit invocation, a new physical machine, current-version upgrade/rollback, and a new image-generation run were not tested in this documentation update. Claude Code remains experimental. See [validation details](dev/VALIDATION.md) and [installation](INSTALL.md) in Chinese.
