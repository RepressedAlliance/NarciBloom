# NarciBloom

Adjustable text for the Steam edition of **Narcissu 10th Anniversary Anthology Project**, with Steam Deck as the first target.

**Current release: [v0.2.0-preview.6](https://github.com/RepressedAlliance/NarciBloom/releases/tag/v0.2.0-preview.6) · Developer preview.** Native Windows and SteamOS packages fix Chinese closing-punctuation tails, add word-boundary protection and align extraction with measurement. Full-story playthroughs remain unverified. See the [compatibility notes](docs/COMPATIBILITY.md) for the exact scope.

See the [root-cause and validation notes](docs/LAYOUT.md) for the native failure, controlled comparisons and remaining limits. Generic word frequencies guide Chinese boundaries; original translation bytes are retained.

The preview.7 candidate on main adds bounded recognition of words missing from the dictionary, with suffix-stable word costs and checks against common-singleton overmerging. Player packages are pending; the downloads below remain preview.6.

- Six in-game sizes: **24 / 28 / 32 / 36 / 40 / 44**, with 36 as the default and an indicator for the current value.
- Persistent size settings and an optional existing local font family; no font installation or system-locale change.
- Readable native dialogs and menus, with Chinese captions for common controls in supported Chinese installations; some fixed prompts remain in English.
- Native Chinese punctuation tables match the renderer's encoding, reducing isolated closing punctuation without editing story text.
- A Chinese paragraph ending with one Han character and closing punctuation can borrow at most one preceding Han character when the measured width fits. Extra leading ASCII spaces have zero display advance; U+3000 spaces use half their native width. Translation bytes, full-width punctuation and spaces within English sentences are retained. This does not provide language segmentation or English whole-word protection.
- Additional page breaks when a long paragraph exceeds the active text area, without moving the artwork or reducing the selected size.

## Two packages, one font core

| Package | Purpose | Windows | SteamOS / Steam Deck |
|---|---|---|---|
| **Fonts** | Keep recognized Japanese, English or supported Chinese story text. No translation included or required. | [Download ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.6/NarciBloom-0.2.0-preview.6-Windows-x64-Fonts.zip) | [Download ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.6/NarciBloom-0.2.0-preview.6-SteamOS-Linux-x64-Fonts.zip) |
| **Chinese** | Includes prepared PC v1.1 translation inputs and credits; font changes are generated locally with the same core. | [Download ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.6/NarciBloom-0.2.0-preview.6-Windows-x64-Chinese.zip) | [Download ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.6/NarciBloom-0.2.0-preview.6-SteamOS-Linux-x64-Chinese.zip) |

Only the recorded Steam anthology versions and PC v1.1 Chinese translation are recognized. Other editions, translation builds and the separate free *Narcissu 1st & 2nd* release are outside this scope. The installer lists stories actually installed on your machine; it does not download the game or DLC.

Translation: **风铃汉化组**. Font features and platform adaptation: **NarciBloom**. Preserve the original translation notices and release link; the Chinese package is free and does not contain the game itself. The [translation-source notes](docs/TRANSLATION.md) explain redistribution conditions and their remaining limits.

## Install or update

Close the game, extract the complete package, then open its native launcher: `NarciBloom.exe` / `NarciBloomChinese.exe` on Windows, or `NarciBloom` / `NarciBloomChinese` in SteamOS desktop mode. The SteamOS installer runs natively; the game continues to launch through Steam with its configured compatibility layer.

Check the anthology's game root folder, select the supported stories you own, and choose **Install / Update**. The Chinese launcher detects its accompanying prepared ZIP; the recognized original RAR is also accepted. **Uninstall & Restore** uses the originals retained in the game's `.narcibloom` folder; keep that folder. Later changes by Steam or another mod are reported as conflicts instead of silently overwritten. Personal saves are protected. See the [installation and recovery guide](docs/INSTALLATION.md).

Existing preview installations can use the new installer to update. Keep the `.narcibloom` record and backups; do not overwrite the translation manually. Release checksums are in [SHA256SUMS.txt](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.6/SHA256SUMS.txt).

In 1+2, open the pause menu → Options → Font / Size. The other stories add size buttons to their existing settings page. Image-based labels do not scale with story text.

During an added page break, settings and history are temporarily unavailable to protect pending text. They become available at the game's next natural paragraph pause. Saving at an added page break resumes from the previous native checkpoint, so some text may need to be reread. Since preview.2, the independent window-title field uses each work's complete English name to avoid Windows code-page garbling; story language and save locations are retained. The remaining paging limitations are not full-story compatibility guarantees.

Preview.3 fixes reproduced blank text after saving/loading a paginated paragraph, history return from a long paragraph, and history input ending an automatic page timer early. It also corrects the save/load UI charset in three older Japanese engines. These fixes have targeted checks; existing save caches are not rewritten, and all stories, fonts, sizes and platform combinations have not been played through.

## What has been checked

Preview.6 has 200 source checks: 196 pass locally with four platform skips. Both CI platform builds and both frozen GUI views pass startup checks. The actual x86 fix completed 624 neutral calls; two reported original records were compared across 20 controlled glyph-width/line-width combinations. The old version had two punctuation-tail breaks and five target-word splits; the new candidate has zero of either, preserving every text byte. Five Chinese and ten Japanese/English build checks remain documented. This version has not yet had a Deck gameplay regression check; controlled widths and GUI startup do not prove actual-font, every-size or full-story behavior. See the [exact scope and remaining limits](docs/COMPATIBILITY.md).

For feedback, include the story and scene, size, game/translation version, OS and Proton version where applicable. Avoid spoilers, personal paths, save uploads and complete game files.

Developers: [setup, APIs and native package builds](docs/DEVELOPMENT.md), [input profiles](docs/source-profiles.json), [version records](docs/VERSIONS.md). Also available: [中文说明](README.md).

Original project code is [MIT licensed](LICENSE). Game and translation content retain their separate ownership; dependency notices are in [THIRD_PARTY.md](THIRD_PARTY.md). This is an independent, unofficial project.
