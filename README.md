# NarciBloom · 水仙舒读

让《水仙》的文字，在掌心舒展开来。

《Narcissu 10th Anniversary Anthology Project》Steam 版的字号与排版改良项目，优先改善 Steam Deck 上的阅读体验。

**当前版本：[v0.2.0-preview.5](https://github.com/RepressedAlliance/NarciBloom/releases/tag/v0.2.0-preview.5) · 开发预览。** 提供 Windows 与 SteamOS 玩家测试包，新增中文短尾行与空白显示调整，保留此前中文设置、标点换行及分页交互修正。尚未验证所有文本、演出和字号组合。

[English](README.en.md) · [兼容性与测试范围](docs/COMPATIBILITY.md) · [开发与构建](docs/DEVELOPMENT.md) · [后续计划](docs/ROADMAP.md) · [更新记录](CHANGELOG.md)

## 做了什么

- 游戏内选择 **24 / 28 / 32 / 36 / 40 / 44** 六档字号，显示当前档位，默认 36。
- 调整正文、角色名及相关文字的字体参数；图片中绘制好的文字不随之缩放。
- 修正 1＋2 的小文本区：大字号下换行时不再每行都清除前文。
- 长段超出当前文本区时分页，继续后显示余文，保留所选字号与文字动画。
- 修正支持的汉化版本中字体窗口标签与按钮错乱，保留中文剧情与字号菜单。
- 中文普通段落只剩单字加收尾标点时，实际宽度允许才从前行借一个汉字；多余行首半角空格不占位，句间全角空白缩为半宽。原译文、全角标点与英文句内空格不改。
- 自动查找 Steam 游戏，按实际安装的故事选择补丁，保留原文件供更新和卸载恢复。

![游戏内字号选择](docs/images/font-size-menu.png)

1＋2 的入口：剧情中打开暂停菜单 → **设定 → 字体 / 字号 → 字号：当前值**。

其他篇章的实现是在原设置页底部增加字号选择；实际验证范围请看兼容性说明。

![一代 44 档连续多行显示](docs/images/multiline-44.png)

## 适用范围

适配 **Steam 十周年合集的受支持日文、英文原版，以及风铃汉化组 PC v1.1**。识别范围包括 1＋2、姬子后日谈、小小的鸢尾花、Zero 和 Sumire；安装器只处理本机已有的故事，不下载或解锁 DLC。免费版《Narcissu 1st & 2nd》（另一款 Steam 应用）及其他补丁版本不在本次支持范围内。

五个故事与三种语言共用字体核心，按各自引擎脚本结构和编码生成对应资源。Windows 与 Steam Deck 的具体抽样结果见[兼容性说明](docs/COMPATIBILITY.md)，**未逐章通关验证**。输入文件标识见[版本记录](docs/VERSIONS.md)及 `docs/source-profiles.json`。

## 两种安装包

| 包名 | 用途 | Windows | SteamOS / Steam Deck |
|---|---|---|---|
| **Fonts** · 独立字体补丁 | 保留当前日文、英文或受支持中文；不含汉化，无需先安装汉化。 | [下载 ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.5/NarciBloom-0.2.0-preview.5-Windows-x64-Fonts.zip) | [下载 ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.5/NarciBloom-0.2.0-preview.5-SteamOS-Linux-x64-Fonts.zip) |
| **Chinese** · 中文整合包 | 风铃 PC v1.1 安装材料、原署名与相同字体功能；无需先运行原汉化程序。 | [下载 ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.5/NarciBloom-0.2.0-preview.5-Windows-x64-Chinese.zip) | [下载 ZIP](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.5/NarciBloom-0.2.0-preview.5-SteamOS-Linux-x64-Chinese.zip) |

Windows 提供完整解压后运行的 `.exe`；SteamOS 提供原生可执行程序，安装器无需 Proton。两种包都需要自有 Steam 游戏。中文原包的转载条件、署名与本地生成方式见[汉化来源说明](docs/TRANSLATION.md)。

## 现在如何使用

下载上表对应 ZIP，**关闭游戏并完整解压**，运行 `NarciBloom.exe`／`NarciBloomChinese.exe`（Windows），或在桌面模式运行 `NarciBloom`／`NarciBloomChinese`（SteamOS）。检查游戏根目录、选择故事，点击「安装 / 更新」，完成后从 Steam 启动游戏。

旧版用户也通过新版安装器更新，保留游戏内的 `.narcibloom` 原文件备份；不要手动覆盖汉化或删除记录。遇到未知版本或文件冲突会停止并显示原因。完整步骤与恢复方法见[安装说明](docs/INSTALLATION.md)，文件校验值见发布页的 [SHA256SUMS.txt](https://github.com/RepressedAlliance/NarciBloom/releases/download/v0.2.0-preview.5/SHA256SUMS.txt)。

源码仓库不包含游戏本体、剧情文本、语音、CG、汉化原文件或玩家存档。开发者请阅读[构建说明](docs/DEVELOPMENT.md)。

## 验证范围与限制

preview.5 核心源码 CI 通过；185项检查中181项通过、4项按平台条件跳过，含新增6项原生显示检查。五部中文真实构建及十组日英只读构建通过；三个引擎族另有实际32位调用检查。SteamOS 本轮仅中文1＋2最终候选完成44档短尾旧新对照、历史打开／返回与单字回答抽样，不能据此认定五部实机、全部字号或全篇通过。此前版本的运行证据单独保留，具体范围见[兼容性说明](docs/COMPATIBILITY.md)。

新增页内等待时，设置和历史暂不可用；到原生段落停顿后恢复。页内存档不能精确恢复到该页，可能需要重读当前段。旧存档缓存不会自动重写，所有剧情／字体／字号组合及 SteamOS 完整自动播放周期等尚未验证；本轮 SteamOS 的 Space 停止自动播放尝试未通过。当前适合玩家试用与反馈，不作全篇无故障保证。

## 反馈

遇到问题请在 Issues 提供：篇章与场景、字号、游戏/汉化版本、设备与 Proton 版本，以及现象截图。请尽量避免剧情剧透，不要公开上传存档或完整游戏文件。

## 许可与致谢

本项目自行编写的代码采用 [MIT](LICENSE) 许可。游戏与汉化内容属于各自权利人，不在本项目许可范围内。

感谢 [majiro-py](https://github.com/trigger-segfault/majiro-py) 和 [evbunpack](https://github.com/mos9527/evbunpack) 提供的基础工具。依赖许可与来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。本项目为非官方阅读体验改良项目，与游戏开发商、发行商及汉化作者无隶属关系。
