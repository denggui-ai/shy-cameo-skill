# Capabilities

[Home](../README.md) · [Examples](CASES.en.md) · [Verification matrix (中文)](dev/VERIFICATION-MATRIX.md) · [Test plan (中文)](dev/NEXT-TESTS.md) · [简体中文](CAPABILITIES.md)

Tell Codex who you want to meet, where you want to go, what you want to wear or what story you want to experience. There are **seven categories and fifteen directions**.

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
| My stage | Perform as a singer or instrumentalist | Experimental, implemented in development; [complete guitar set and three interaction selections](cases/virtual-my-stage-guitar.md) accepted, plus earlier guitar/drum single-image observations |
| Attend their concert | See a solo artist, band or virtual singer | Experimental; [Tokyo 1992 audience set](cases/virtual-gnr-tokyo.md) received overall positive feedback; not proof of precise history or reliable recognition across artists |

“Existing accepted real-person set” means a complete five-image set was reviewed and accepted by its subject. Older documents call this “stable”; it is not a guarantee. The thirteen virtual-model sets in the gallery broaden the examples, without promoting the real-person validation tiers. These POCs used virtual-subject wording adaptations and do not establish an automated real-person CLI run.

## Concert directions in development

These two directions are **not included in the v1.0.3-rc.1 release**. “My stage” makes you a singer, guitarist, drummer, bassist or keyboardist while preserving your own identity. Intense performance, expressive faces, forceful playing and dynamic camera angles can create a wild concert atmosphere; likeness and instrument anatomy still need review. “Attend their concert” places you in the audience, with a real solo artist, band or virtual singer performing on a distant stage. Clothing, instruments, movements and a specific tour design carry recognition; performers do not have clear facial detail.

Each is an imagined five-shot story, from preparation or arrival to the final bow or departure. It is not evidence of real attendance. Close celebrity photos, backstage meetings and accompanying fictional characters in the audience are outside these new modes. The Tokyo audience set received positive overall feedback. The owner accepted the complete guitar set and explicitly approved showcase inclusion; earlier single-image guitar and drum examples also exist. These virtual-subject observations do not establish real-person likeness during large movements.

My Stage can plan playing back-to-back with a bassist, cueing a drummer, exchanging musical phrases and taking a shared bow with original adult bandmates. The user remains the main subject; bandmates appear from behind or the rear side. One or two interaction shots can add variety, while an explicit solo preference is retained. The owner selected a bass duet, drummer response and revised final salute. Four calls produced the three selections, including one requested correction and no automatic retries. These are virtual-subject supplement images, not a new five-shot set or a reliability study. Real performers in the audience mode remain on a distant stage.

Tickets, programmes, fan items and tour merchandise can be selected for the artist, era and audience culture. Their acquisition, use and storage can carry the story; empty hands remain an option. Official designs require evidence, and modern fan items are not assumed for historical concerts. This newer guidance has no matching complete-set image validation.

Classic concert stories generate the core stage image first and display the images in story order. The default limit is five calls. Only an explicitly authorized, materially different audience-story alternative raises the combined limit to six; five returned images are not guaranteed, and rejection or unknown-result records are preserved.

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

At most five generation calls are submitted for a set. Submitted failures may use quota; a failed first image cancels the remaining shots, and retries are not automatic. Originals are retained without re-encoding; optional visible AI labels are separate copies. The public gallery includes resized web copies and original PNGs, identified in each manifest.

The skill does not handle minor subjects, close photos with real celebrities, multiple real-person identity-photo subjects, landscape output, automatic beauty/slimming edits, on-image text, automatic posting, or a full asset-management center. Reference atmosphere images are interpreted in words; precise light/color transfer is not established.

Current release installation and discovery passed for both direct-skill and plugin-ZIP paths on macOS / Codex CLI 0.161.0 in isolated configurations. One explicit first-use storyboard request passed with image generation disabled. Desktop clicks, implicit invocation, a new physical machine, current-version upgrade/rollback, and a new image-generation run were not tested in this documentation update. Claude Code remains experimental. See [validation details](dev/VALIDATION.md) and [installation](INSTALL.md) in Chinese.
