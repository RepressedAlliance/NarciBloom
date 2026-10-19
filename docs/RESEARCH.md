# 仓库组织与分发方式调研

调研日期：2026-10-20。目标是把《水仙》的字号与排版改良逐步维护为可分享的补丁。以下为从项目原仓库、文档及玩家教程得到的事实，再据此作出适合本项目规模的取舍；相似项目的实现不等于已经适配水仙。

## 同类项目

| 项目 | 相关做法 | NarciBloom 的取舍 |
|---|---|---|
| [STS2 Font Size Patcher](https://github.com/aliceisjustplaying/sts2-font-size-patcher) | 面向 Deck 小字体问题；配置与构建分开；首页有示例，另设指南与维护笔记 | 采用简短首页、截图、兼容性记录与独立开发文档。其补丁针对 Godot/.NET，不能复用于 Majiro |
| [07th-Mod Python Patcher](https://github.com/07th-mod/python-patcher) | 多款视觉小说共用跨平台安装器，以 JSON 定义安装内容，将玩家下载入口与开发说明区分 | 借鉴版本与篇章识别；目前维持一个小仓库，不照搬其多仓库/网页安装器架构 |
| [SenPatcher](https://github.com/AdmiralCurtiss/SenPatcher) | 明确列出支持的游戏/版本；分列 Windows GUI、手动及 Steam Deck 用法；有移除/恢复入口 | 将游戏/汉化版本识别和卸载作为首个可分发安装包的要求，而非只提供覆盖文件 |
| [Katawa Shoujo HD Patch](https://github.com/Ultralavaboy/KatawaShoujoHDPatch) | 用画面比较说明视觉改良的结果 | 目前放实际设置与多行截图；之后以同场景、同画幅做真正的前后对比，不用不同剧情截图冒充对照 |
| [Katawa Shoujo: Re-Engineered](https://github.com/fleetingheart/ksre) | 可访问性与多语言作为明确功能，代码和原作资源分别说明许可；这是 GitHub 镜像 | 借鉴功能与权属边界。该项目涉及引擎重做，规模远大于本项目，不将其作为当前架构模板 |
| [Furoshiki](https://github.com/yy487/Furoshiki) | 将字体管理、文本处理、虚拟文件层等拆成模块；作者说明 Wine/Proton 部分路径可用，同时指出区域设置差异 | 作为未来减少直接修改文件的技术参考。项目较新、且未在本游戏验证，当前不引入新的运行时 Hook 框架 |

## 玩家侧交叉验证

- [Steam 社区安装教程](https://steamcommunity.com/sharedfiles/filedetails/?id=3442843599) 单独介绍自动与手动安装，说明自动安装未成功时仍需要可理解的替代流程。教程是个人说明，不是安装成功率的统计。
- [ycx Studios 的 07th-Mod 安装指南](https://higurashi.ycx-studios.site/guide/07th-mod/main.html) 大部分译自官方，不能整体视为独立证据；其中汉化组另行给出了针对国内下载体验的手动安装建议。这提醒我们避免安装时必须在线拉取许多资源，但不能据此认定所有用户的自动安装都会失败。
- 检索发现 Reddit 有视觉小说在 Deck 上字体太小的讨论；具体页面未能成功打开，因此不将搜索摘要作为项目设计结论的关键佐证。

## 仓库组织建议

采用一个仓库，根目录用简短中英文 README、LICENSE、第三方说明与 CHANGELOG；`tools/` 管理构建逻辑，`tests/` 放不带游戏内容的检查，`docs/` 记录使用范围、技术说明和计划。安装包将来放 Releases，构建结果、游戏源文件和个人环境留在被忽略的本地目录。

仓库与成品发布分开：现在公开开发源码，完成版本识别及安装/卸载后发布预发布包，经过实际游玩后再按验证范围发布稳定版。[GitHub 的 Releases 说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)与[预发布设置](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)支持这种区分。

首页按“做什么 → 效果 → 适用版本/验证范围 → 如何使用 → 反馈”排列。技术来龙去脉留在开发文档，不把维护者的操作记录当成普通玩家的安装指南。

## 发布前需要补齐的本项目问题

1. 现有本机代码含固定路径和一次性部署前提：本次源码整理已分离本地路径，未保留远程连接和一次性安装器。
2. 1＋2 汉化的虚拟文件优先级和 DLL 指令位置与版本有关：先补齐版本识别，再让普通玩家安装。
3. 只能确认部分场景：已实测的内容逐项写明，不能把“覆盖五个模块的代码”写成“五个篇章完整验证”。
4. 解包目录含完整游戏/汉化内容：仅在玩家自己的本地生成，不随源码与安装包原样分发。
5. 代码、依赖及游戏资源的许可分开：自行代码采用 MIT，依赖分别保留许可；开源代码不代表拥有原作资源的分发授权。[GitHub 许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)用于核对源码许可的基本含义，不用于推定第三方素材授权。

## 名称

最终选择 **NarciBloom · 水仙舒读**：Narci 呼应 Narcissu；Bloom 同时呼应水仙花与文字展开。用途副标题为“水仙十周年合集字号与排版改良”。名称不绑定 Steam Deck，便于将来在实际验证后加入 Windows 支持。

曾比较 NarciLens（偏清晰阅读/镜片意象）与 NarciType（直指字体）。当日 GitHub 仓库名称检索未找到这三个名称的同名公开项目；这仅表示该次检索结果，不保证全网唯一，也不是商标核验。
